ec2-snapshot-tool
=================
ec2-snapshot-tool is a python script to create/purge/copy snapshots of your EB volumes. 

#Prerequisites
- *python3-pip*: Python 3 version of the package pip
- *boto3*: Amazon Web Services (AWS) SDK for Python.

Usage
==========
1. Install and configure Python and Boto (See: https://boto3.readthedocs.org/en/latest/guide/quickstart.html#installation)
2. Create a snapshot user in IAM and put the key and secret in the config file
3. Create a security policy for this user (see the iam.policy.sample)
4. Copy config.sample to config.py
5. Decide how many snapshots you want to keep and change this in config.py
6. Change the Region and backup_region in the config.py file
7. Install the script in the cron: 

		# chmod +x ec2_snapshot.py
		# crontab -e
		0 5 * * * /opt/ec2-snapshot-tool/ec2_snapshot.py create
		30 5 * * * /opt/ec2-snapshot-tool/ec2_snapshot.py copy
		40 5 * * * /opt/ec2-snapshot-tool/ec2_snapshot.py delete
		40 5 * * * /opt/ec2-snapshot-tool/ec2_snapshot.py delete -keep 1 --region 'us-east-1'

Additional Notes
=========
The user that executes the script needs the following policies: see iam.policy.sample
