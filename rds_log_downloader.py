import os
import json
import argparse
import boto3
from botocore.exceptions import NoRegionError, ClientError
from time import sleep

def get_rds(region):
    try:
        return boto3.client("rds", region)
    except NoRegionError:
        print(f"AWS region not set, switching to us-east-1")
        return boto3.client("rds","us-east-1")
    except Exception as e:
        print(str(e))
        return None

def get_db_logs(rds, dbid, logfilter):
    try:
        return rds.describe_db_log_files(
            DBInstanceIdentifier=dbid,
            FilenameContains=logfilter,
        )['DescribeDBLogFiles']
    except Exception as e:
        print(str(e))
        return None

def check_for_truncation(log_data):
    """Check if the log data contains the truncation message."""
    return "[Your log message was truncated]" in log_data


def get_log_output_path(logfile):
    return os.path.join(os.getcwd(), logfile.split('/')[1])


def get_truncated_artifact_path(logfile):
    base = logfile.split('/')[1]
    return os.path.join(os.getcwd(), f"{base}_truncated_lines")


class AdaptiveChunkSizer:
    """
    Remembers successful chunk sizes across downloads and picks the next request size.

    During an initial warmup window it uses the minimum successful size seen so far.
    After warmup it keeps a rolling minimum and occasionally probes a larger size when
    several consecutive chunks succeed without truncation.
    """

    def __init__(self, initial_size, max_size, min_lines=100, warmup_chunks=3, probe_after_clean=3):
        self.max_size = max_size
        self.min_lines = min_lines
        self.warmup_chunks = warmup_chunks
        self.probe_after_clean = probe_after_clean
        self.chunk_size = initial_size
        self.successful_sizes = []
        self.consecutive_clean = 0

    def next_size(self):
        return self.chunk_size

    def update(self, successful_chunk_size, had_truncation):
        self.successful_sizes.append(successful_chunk_size)

        if had_truncation:
            self.consecutive_clean = 0
        else:
            self.consecutive_clean += 1

        window = self.successful_sizes[-self.warmup_chunks:]
        previous_size = self.chunk_size
        self.chunk_size = max(self.min_lines, min(window))

        if had_truncation:
            print(f"Adaptive chunk size: using {self.chunk_size} lines for next chunk (reduced due to truncation)")
        elif len(self.successful_sizes) == self.warmup_chunks:
            print(f"Warmup complete: using {self.chunk_size} lines (min of last {self.warmup_chunks} successful chunks)")
        elif self.consecutive_clean >= self.probe_after_clean:
            probe_size = min(self.max_size, int(self.chunk_size * 1.5))
            if probe_size > self.chunk_size:
                print(f"Probing larger chunk size: {probe_size} lines after {self.consecutive_clean} clean downloads")
                self.chunk_size = probe_size
                self.consecutive_clean = 0
        elif self.chunk_size != previous_size and not had_truncation:
            print(f"Adaptive chunk size: using {self.chunk_size} lines for next chunk")


def download_db_logs(rds, dbid, logfile, token, lines, min_lines=100):
    """
    Download a chunk of log data, verifying it's not truncated.
    If truncation is detected, retry with a smaller chunk size.
    
    Args:
        rds: RDS client
        dbid: Database instance identifier
        logfile: Log file name
        token: Marker token for pagination
        lines: Number of lines to download
        min_lines: Minimum chunk size to avoid infinite loops (default: 100)
    
    Returns:
        tuple: (has_more_data, new_token, successful_chunk_size, had_truncation_retries,
                min_truncation_written)
    """
    initial_lines = lines
    current_lines = lines
    max_retries = 10  # Prevent infinite loops
    
    for retry in range(max_retries):
        try:
            log = rds.download_db_log_file_portion(
                DBInstanceIdentifier=dbid,
                LogFileName=logfile,
                NumberOfLines=current_lines,
                Marker=token
            )
            
            if log['ResponseMetadata']['HTTPStatusCode'] == 200:
                log_data = log['LogFileData']
                
                # Check for truncation
                if check_for_truncation(log_data):
                    if current_lines <= min_lines:
                        print(f"Warning: Truncation detected but chunk size ({current_lines}) is at minimum. Writing anyway.")
                        # Write it anyway if we're at minimum
                        with open(get_log_output_path(logfile), 'a+') as f:
                            f.write(log_data)
                        return log['AdditionalDataPending'], log['Marker'], current_lines, True, True
                    else:
                        # Reduce chunk size and retry
                        new_lines = max(min_lines, current_lines // 2)
                        print(f"Truncation detected in chunk. Retrying with smaller size: {new_lines} lines (was {current_lines})")
                        current_lines = new_lines
                        sleep(1)  # Brief wait before retry
                        continue
                
                # No truncation detected, write the data
                with open(get_log_output_path(logfile), 'a+') as f:
                    f.write(log_data)
                
                return log['AdditionalDataPending'], log['Marker'], current_lines, current_lines < initial_lines, False
            else:
                print(f"There was an error downloading last file part. HTTP Status Code: {log['ResponseMetadata']['HTTPStatusCode']}")
                print(f"Waiting another 30 seconds before retrying. Retries: {log['ResponseMetadata']['RetryAttempts']}")
                sleep(30)
                return True, token, current_lines, False, False
        except IOError as e:
            print(str(e))
            return False, 0, current_lines, False, False
        except Exception as e:
            print(str(e))
            return False, 0, current_lines, False, False
    
    # If we exhausted retries, write what we have
    print(f"Warning: Max retries reached. Writing chunk with {current_lines} lines.")
    try:
        log = rds.download_db_log_file_portion(
            DBInstanceIdentifier=dbid,
            LogFileName=logfile,
            NumberOfLines=current_lines,
            Marker=token
        )
        if log['ResponseMetadata']['HTTPStatusCode'] == 200:
            with open(get_log_output_path(logfile), 'a+') as f:
                f.write(log['LogFileData'])
            return log['AdditionalDataPending'], log['Marker'], current_lines, current_lines < initial_lines, False
    except Exception as e:
        print(f"Error in final retry: {str(e)}")
    
    return False, 0, current_lines, False, False


def recover_truncated_chunks(rds, dbid, logfile, chunks, output_path, wait=0):
    """
    Re-download truncated-at-minimum chunks one line at a time into a separate artifact.
    """
    total_lines = 0
    still_truncated = 0

    with open(output_path, 'w') as artifact:
        for chunk_index, chunk in enumerate(chunks, start=1):
            marker = chunk['start_marker']
            print(f"Recovering chunk {chunk_index}/{len(chunks)} ({chunk['line_count']} lines)...")
            for _ in range(chunk['line_count']):
                try:
                    log = rds.download_db_log_file_portion(
                        DBInstanceIdentifier=dbid,
                        LogFileName=logfile,
                        NumberOfLines=1,
                        Marker=marker,
                    )
                except Exception as e:
                    print(f"Error recovering chunk {chunk_index}: {e}")
                    break

                if log['ResponseMetadata']['HTTPStatusCode'] != 200:
                    print(f"Error recovering chunk {chunk_index}: HTTP {log['ResponseMetadata']['HTTPStatusCode']}")
                    break

                log_data = log['LogFileData']
                artifact.write(log_data)
                total_lines += 1
                if check_for_truncation(log_data):
                    still_truncated += 1

                marker = log['Marker']
                if wait:
                    sleep(float(wait))

    recovered = total_lines - still_truncated
    return len(chunks), total_lines, recovered, still_truncated


def main():
    # Read args
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', action='store', dest='dbid', required=True, help='RDS Instance Identifier')
    parser.add_argument('-r', action='store', dest='region', required=False, default='us-east-1', help='AWS Region for the RDS instance (default: us-east-1)')
    parser.add_argument('-f', action='store', dest='logfilter', required=False, default='postgresql', help='String for filtering log files to download (default: postgresql). HINT: You should use the date contained in the log file name')
    parser.add_argument('-l', action='store', dest='lines', required=False, default=2000, help='Number of lines to download per iteration (default: 2000)')
    parser.add_argument('-w', action='store', dest='wait', required=False, default=1, help='Number of seconds to wait before downloading the next log chunk (default: 1)')
    parser.add_argument('-F', action='store_true', dest='force_truncated', required=False, default=False, help='Re-download minimum-size truncated chunks line-by-line into <logname>_truncated_lines (default: off)')
    args = parser.parse_args()
    rds = get_rds(args.region)

    for db_log in get_db_logs(rds, args.dbid, args.logfilter):
        lineup = '\033[1A'
        lineclear = '\x1b[2K'
        token = '0'
        count = 1
        total_lines_downloaded = 0

        print(f"Processing logfile {db_log['LogFileName']}")

        max_lines = int(args.lines)
        sizer = AdaptiveChunkSizer(max_lines, max_lines)
        truncated_chunks = []

        chunk_size = sizer.next_size()
        start_marker = token
        istheremore, token, successful_chunk_size, had_truncation, min_truncation = download_db_logs(
            rds, args.dbid, db_log['LogFileName'], token, chunk_size
        )
        if args.force_truncated and min_truncation:
            truncated_chunks.append({'start_marker': start_marker, 'line_count': successful_chunk_size})
        total_lines_downloaded += successful_chunk_size
        sizer.update(successful_chunk_size, had_truncation)

        while istheremore:
            print('Lines downloaded: {}. Waiting {} seconds'.format(total_lines_downloaded, args.wait))
            sleep(float(args.wait))
            chunk_size = sizer.next_size()
            start_marker = token
            istheremore, token, successful_chunk_size, had_truncation, min_truncation = download_db_logs(
                rds, args.dbid, db_log['LogFileName'], token, chunk_size
            )
            if args.force_truncated and min_truncation:
                truncated_chunks.append({'start_marker': start_marker, 'line_count': successful_chunk_size})
            total_lines_downloaded += successful_chunk_size
            sizer.update(successful_chunk_size, had_truncation)
            count = count + 1
            print(lineup, end=lineclear)

        if args.force_truncated and truncated_chunks:
            artifact_path = get_truncated_artifact_path(db_log['LogFileName'])
            print(f"Recovering {len(truncated_chunks)} truncated chunk(s) line-by-line into {artifact_path}")
            chunk_count, total_lines, recovered, still_truncated = recover_truncated_chunks(
                rds, args.dbid, db_log['LogFileName'], truncated_chunks, artifact_path, args.wait
            )
            print(
                f"Recovery complete: {chunk_count} chunk(s), {total_lines} line(s) written to artifact, "
                f"{recovered} fully recovered, {still_truncated} still truncated at 1 line"
            )

if __name__ == '__main__':
    main()