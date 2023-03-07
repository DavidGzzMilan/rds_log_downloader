# rds_log_downloader
This repository contains a Python script to download RDS PostgreSQL log files using Boto3 SDK for Python. 

## AWS Credentials
The AWS credentials should be already available, accordingly with the [online documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html#configuring-credentials) the following are supported by this script:

```
- Environment variables
- Shared credential file (~/.aws/credentials)
- AWS config file (~/.aws/config)
- Assume Role provider
- Boto2 config file (/etc/boto.cfg and ~/.boto)
- Instance metadata service on an Amazon EC2 instance that has an IAM role configured
```

## Prerequisites
This script was written and tested using Python 3.6. It is necessary to have this Python version available in the system.

## Executing this script
Having Python 3.6 installed, to get this script running you need to follow the next steps:

1. Create a virtual environment directory (if not exists).
``` 
mkdir -p ~/python_venvs/venv_3.6
```
2. Create the python virtual environment.
```
virtualenv-3 --python=$(which python3.6) ~/python_venvs/venv_3.6
```
3. Activate the virtual environment.
```
source ~/python_venvs/venv_3.6/bin/activate
```
> Note the prompt should show the activated venv: `(venv_3.6) $`

4. Verify the python version within the venv, it should be `python3.6`, also check the pip version is working for the same python.
```
python --version
pip --version
```

5. Move to the project directory.
```
cd rds_log_downloader/
```

6. Install all the pip requirements from the [requirements.txt](requirements.txt) file.
```
pip install -r requirements.txt
```

7. Execute the python code.
```
python rds_log_downloader.py --help

usage: rds_log_downloader.py [-h] -i DBID [-f LOGFILTER] [-l LINES] [-w WAIT]

optional arguments:
  -h, --help    show this help message and exit
  -i DBID       RDS Instance Identifier
  -f LOGFILTER  String for filtering log files to download (default:
                postgresql). HINT: You should use the date contained in the
                log file name
  -l LINES      Number of lines to download per iteration (default: 2000)
  -w WAIT       Number of seconds to wait before downloading the next log
                chunk (default: 1)
```