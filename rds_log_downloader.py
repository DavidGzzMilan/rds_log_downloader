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
        tuple: (has_more_data, new_token, actual_lines_downloaded)
    """
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
                        with open(os.path.join(os.getcwd(), logfile.split('/')[1]), 'a+') as f:
                            f.write(log_data)
                        return log['AdditionalDataPending'], log['Marker'], current_lines
                    else:
                        # Reduce chunk size and retry
                        new_lines = max(min_lines, current_lines // 2)
                        print(f"Truncation detected in chunk. Retrying with smaller size: {new_lines} lines (was {current_lines})")
                        current_lines = new_lines
                        sleep(1)  # Brief wait before retry
                        continue
                
                # No truncation detected, write the data
                with open(os.path.join(os.getcwd(), logfile.split('/')[1]), 'a+') as f:
                    f.write(log_data)
                
                return log['AdditionalDataPending'], log['Marker'], current_lines
            else:
                print(f"There was an error downloading last file part. HTTP Status Code: {log['ResponseMetadata']['HTTPStatusCode']}")
                print(f"Waiting another 30 seconds before retrying. Retries: {log['ResponseMetadata']['RetryAttempts']}")
                sleep(30)
                return True, token, current_lines
        except IOError as e:
            print(str(e))
            return False, 0, current_lines
        except Exception as e:
            print(str(e))
            return False, 0, current_lines
    
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
            with open(os.path.join(os.getcwd(), logfile.split('/')[1]), 'a+') as f:
                f.write(log['LogFileData'])
            return log['AdditionalDataPending'], log['Marker'], current_lines
    except Exception as e:
        print(f"Error in final retry: {str(e)}")
    
    return False, 0, current_lines

def main():
    # Read args
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', action='store', dest='dbid', required=True, help='RDS Instance Identifier')
    parser.add_argument('-r', action='store', dest='region', required=False, default='us-east-1', help='AWS Region for the RDS instance (default: us-east-1)')
    parser.add_argument('-f', action='store', dest='logfilter', required=False, default='postgresql', help='String for filtering log files to download (default: postgresql). HINT: You should use the date contained in the log file name')
    parser.add_argument('-l', action='store', dest='lines', required=False, default=2000, help='Number of lines to download per iteration (default: 2000)')
    parser.add_argument('-w', action='store', dest='wait', required=False, default=1, help='Number of seconds to wait before downloading the next log chunk (default: 1)')
    args = parser.parse_args()
    rds = get_rds(args.region)

    for db_log in get_db_logs(rds, args.dbid, args.logfilter):
        lineup = '\033[1A'
        lineclear = '\x1b[2K'
        token = '0'
        count = 1
        total_lines_downloaded = 0

        print(f"Processing logfile {db_log['LogFileName']}")
        
        istheremore, token, actual_lines = download_db_logs(rds, args.dbid, db_log['LogFileName'], token, int(args.lines))
        total_lines_downloaded += actual_lines
        while istheremore:
            print('Lines downloaded: {}. Waiting {} seconds'.format(total_lines_downloaded, args.wait))
            sleep(float(args.wait))
            istheremore, token, actual_lines = download_db_logs(rds, args.dbid, db_log['LogFileName'], token, int(args.lines))
            total_lines_downloaded += actual_lines
            count = count + 1
            print(lineup, end=lineclear)

if __name__ == '__main__':
    main()