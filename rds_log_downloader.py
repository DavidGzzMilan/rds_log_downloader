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

def download_db_logs(rds, dbid, logfile, token, lines):
    try:
        log = rds.download_db_log_file_portion(
            DBInstanceIdentifier=dbid,
            LogFileName=logfile,
            NumberOfLines=lines,
            Marker=token
        )
        if log['ResponseMetadata']['HTTPStatusCode'] == 200:
            with open(os.path.join(os.getcwd(), logfile.split('/')[1]), 'a+') as f:
                f.write(log['LogFileData'])
            return log['AdditionalDataPending'], log['Marker']
        else:
            print(f"There was an error downloading last file part. HTTP Status Code: {log['ResponseMetadata']['HTTPStatusCode']}")
            print(f"Waiting another 30 seconds before retrying. Retries: {log['ResponseMetadata']['RetryAttempts']}")
            sleep(30)
            return True, token
    except IOError as e:
        print(str(e))
        return False, 0
    except Exception as e:
        print(str(e))
        return False, 0

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

        print(f"Processing logfile {db_log['LogFileName']}")
        
        istheremore, token = download_db_logs(rds, args.dbid, db_log['LogFileName'], token, int(args.lines))
        while istheremore:
            print('Lines downloaded: {}. Waiting {} seconds'.format(int(args.lines) * count, args.wait))
            sleep(float(args.wait))
            istheremore, token = download_db_logs(rds, args.dbid, db_log['LogFileName'], token, int(args.lines))
            count = count + 1
            print(lineup, end=lineclear)

if __name__ == '__main__':
    main()