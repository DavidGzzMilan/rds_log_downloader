#!/bin/bash

set -eu

# shellcheck disable=SC2155
declare -r PROGNAME="$(basename "${0}")"
declare -r PARAMS=':hdc:i:j:'
declare -r PYTHON_SCRIPT='
import os
import json
import boto3
from botocore.exceptions import NoRegionError, ClientError

def get_rds():
    try:
        return boto3.client("rds")
    except NoRegionError:
        print(f"AWS region not set, switching to us-east-1")
        return boto3.client("rds","us-east-1")
    except Exception as e:
        print(string(e))
        return None

def get_db_logs(rds, dbid, logdate):
    try:
        if dbinstance and 'InstanceCreateTime' in dbinstance:
            return rds.describe_db_log_files(
                DBInstanceIdentifier=dbid,
                FilenameContains=logdate,
                #FileLastWritten=int((dbinstance['InstanceCreateTime'] - timedelta(minutes=5)).timestamp()*1e3),
            )['DescribeDBLogFiles']
        else:
            return []
    except Exception as e:
        print(string(e))
        return None

def download_db_logs(dbid, logfile, token):
    try:
        log = rds.download_db_log_file_portion(
            DBInstanceIdentifier=dbid,
            LogFileName=logfile,
            Marker=token
        )
        with open(os.path.join(os.getcwd(), logfile), 'a+') as f:
            f.write(log['LogFileData'])
        return log['AdditionalDataPending'], log['Marker']
    except IOError as e:
        print(string(e))
    except Exception as e:
        print(string(e))

def main():
    rds = get_rds()
    dbid = ""
    logdate = ""

    for db_log in get_db_logs(rds, dbid, logdate):
        print(f"Processing logfile {db_log['LogFileName']}")
        token = '0'
        istheremore, token = download_db_logs(dbid, db_log['LogFileName'], token)
        while istheremore:
            istheremore, token = rds_target.download_db_log(dbid, db_log['LogFileName'], token)


if __name__ == '__main__':
    main()
'

declare -i DEBUG=0

declare CLUSTER=all
declare INVENTORY_OUTPUT="/etc/ansible/hosts/autoscaling-rds"
declare JSON_OUTPUT="/etc/rdba/autoscaling-rds.json"
declare QUERY=

function usage {
    local -i status="${1}"

    echo -e "
    #Usage: ${PROGNAME} [-hdv]
    #
    #   -h  Show this information
    #   -d  Enable debugging
    #
    #   -c  Filter for cluster (default: all)
    #   -i  Inventory filename
    #   -j  JSON filename
    #
    " | sed -r 's/^[[:space:]]+//g; s/#//g'

    exit "${status}"
}

function parse {
    python3 -c "${PYTHON_SCRIPT}"
}

#trap cleanup EXIT
#trap die INT QUIT ABRT SEGV TERM KILL

while getopts "${PARAMS}" opt
do
    case ${opt} in
        h)  usage 0;;
        d)  DEBUG=1;;
        c)  CLUSTER="${OPTARG}";;
        i)  INVENTORY_OUTPUT="${OPTARG}";;
        j)  JSON_OUTPUT="${OPTARG}";;
        \?) echo "Missing a value for ${OPTARG}"; usage 2 ;;
        *)  echo "Unknown option ${OPTARG}"; usage 1 ;;
    esac
done

test "${DEBUG}" -eq 0 || set +x

case "${CLUSTER}" in
    all) QUERY=".DBInstances[] | {status: .DBInstanceStatus, engine: .Engine, instance: .DBInstanceIdentifier, cluster: .DBClusterIdentifier, address: .Endpoint.Address, port: .Endpoint.Port}";;
    *)   QUERY=".DBInstances[] | select(.DBClusterIdentifier == \"${CLUSTER}\")  | {status: .DBInstanceStatus, engine: .Engine, instance: .DBInstanceIdentifier, cluster: .DBClusterIdentifier, address: .Endpoint.Address, port: .Endpoint.Port}";;
esac

if [ -f "${JSON_OUTPUT}" ]; then
    jq -cr "${QUERY}" "${JSON_OUTPUT}" | parse > "${INVENTORY_OUTPUT}"
else
    aws rds describe-db-instances | jq -cr "${QUERY}" | parse > "${INVENTORY_OUTPUT}"
fi