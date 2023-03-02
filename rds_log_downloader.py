import os
import json
import boto3
from botocore.exceptions import NoRegionError, ClientError
from time import sleep

def get_rds():
    try:
        return boto3.client("rds")
    except NoRegionError:
        print(f"AWS region not set, switching to us-west-2")
        return boto3.client("rds","us-west-2")
    except Exception as e:
        print(str(e))
        return None

def get_db_logs(rds, dbid, logdate):
    try:
        return rds.describe_db_log_files(
            DBInstanceIdentifier=dbid,
            FilenameContains=logdate,
            #FileLastWritten=int((dbinstance['InstanceCreateTime'] - timedelta(minutes=5)).timestamp()*1e3),
        )['DescribeDBLogFiles']
    except Exception as e:
        print(str(e))
        return None

def download_db_logs(rds, dbid, logfile, token):
    try:
        log = rds.download_db_log_file_portion(
            DBInstanceIdentifier=dbid,
            LogFileName=logfile,
            NumberOfLines=1000,
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
    rds = get_rds()
    dbid = "prod-webapp-postgres-usw2"
    logdate = "2023-02-26"

    for db_log in get_db_logs(rds, dbid, logdate):
        print(f"Processing logfile {db_log['LogFileName']}")
        token = '0'
        istheremore, token = download_db_logs(rds, dbid, db_log['LogFileName'], token)
        while istheremore:
            print('Waiting 2secs...')
            sleep(2)
            istheremore, token = download_db_logs(rds, dbid, db_log['LogFileName'], token)

if __name__ == '__main__':
    main()