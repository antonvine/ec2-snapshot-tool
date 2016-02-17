#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import boto3
import botocore
import os, sys
import requests
import argparse
import logging
import six
from datetime import datetime
from config import config

aws_access_key = config['aws_access_key']
aws_secret_key = config['aws_secret_key']
ec2_region = config['ec2_region']
time_interval = config['time_interval']

# Setup logging
logging.basicConfig(filename=config['log_file'], level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%m/%d/%Y %H:%M:%S')

# Setup boto3 client connection
def ec2_connect(aws_access_key=aws_access_key, aws_secret_key=aws_secret_key, ec2_region=ec2_region):
    if aws_access_key:
        client = boto3.client('ec2', aws_access_key_id=aws_access_key, aws_secret_access_key=aws_secret_key, region_name=ec2_region)
    else:
        client = boto3.client('ec2', region_name=ec2_region)
    return client

# Get current instance id from metadata service
def get_instance_id():
    try:
        response = requests.get('http://169.254.169.254/latest/meta-data/instance-id')
    except:
        logging.error('    Unable to get current instance_id from metadata service.')
        sys.exit()
    return response.text

# Get current instance region from metadata service
# Not yet implemented in boto3 (https://github.com/boto/boto3/issues/313)
def get_instance_region():
    try:
        response = requests.get('http://169.254.169.254/latest/meta-data/placement/availability-zone')
    except:
        logging.error('    Unable to get current availability zone from metadata service.')
        sys.exit()
    return response.text[:-1]

# Get instance attached BlockDevices (volumes)
def get_instance_volumes(instance):
    try:
        response = client.describe_instances(InstanceIds=[instance])
        for r in response['Reservations']:
            for inst in r['Instances']:
                volumes = inst['BlockDeviceMappings']

    except:
        logging.error('    Unable to get block devices atatched to instance %s.', instance)
    return volumes

# Get volume completed snapshots
def get_volume_snapshots(volume):
    try:
        snapshots = client.describe_snapshots(Filters=[{
            'Name': 'status',
            'Values': 'completed',
            'Name': 'tag-value',
            'Values': [volume]
        }])
    except:
        logging.error('    Unable to get volume %s snapshots.', volume)
        snapshots = None
    return snapshots['Snapshots']

# Get resource tags
def get_resource_tags(resource_id):
    resource_tags = {}
    if resource_id:
        tags = client.describe_tags(Filters=[{ 'Name': 'resource-id', 'Values': [resource_id] }])
        for tag in tags['Tags']:
            resource_tags[tag['Key']] = tag['Value']
    return resource_tags

# Create volume snapshot
def create_snapshot(volume):
    vol_tags = get_resource_tags(volume)
    description = '%(name)s snapshot of %(volume)s at %(date)s' % {
        'name': vol_tags['Name'],
        'volume': volume,
        'date': datetime.today().strftime('%d-%m-%Y %H:%M:%S')
    }
    try:
        logging.info('    Creating snapshot of volume %s...', volume)
        vol_snapshot = client.create_snapshot(
            VolumeId=volume,
            Description=description
        )
        logging.info('    Snapshot %s of volume %s created successfully.', vol_snapshot['SnapshotId'], volume)
        try:
            logging.info('      Creating tag name for snapshot %s...', vol_snapshot['SnapshotId'])
            client.create_tags(
                Resources=[vol_snapshot['SnapshotId']],
                Tags=[{
                    'Key': 'Name',
                    'Value': volume
            }])
            logging.info('      Name tag for snapshot %s created successfully.', vol_snapshot['SnapshotId'])
        except:
            logging.error('    Unable to create tags for snapshot %s.', vol_snapshot['SnapshotId'])
    except botocore.exceptions.ClientError as e:
        logging.error('    Unable to create snapshot of volume %s', volume)
        logging.error('Exception: %s', e)

# Purge volume old snapshots in specific region
def purge_snapshot(volume, keep, region):
    global client
    client = ec2_connect(aws_access_key=aws_access_key, aws_secret_key=aws_secret_key, ec2_region=region)
    logging.info('    Searching for snapshots for volume %s...', volume)
    vol_snapshots = get_volume_snapshots(volume)
    sorted_vol_snapshots = sorted(vol_snapshots, key=lambda k: k['StartTime'], reverse=False)
    delta = len(sorted_vol_snapshots) - keep
    logging.info('    %s snapshots will be deleted.', delta)
    for i in range(delta):
        logging.info('    Purging snapshot %s...', sorted_vol_snapshots[i]['SnapshotId'])
        try:
            response = client.delete_snapshot(
                SnapshotId=sorted_vol_snapshots[i]['SnapshotId']
            )
            logging.info('    Snapshot %s purged successfully.', sorted_vol_snapshots[i]['SnapshotId'])
        except botocore.exceptions.ClientError as e:
            logging.error('    Unable to purge snapshot %s. Please check your IAM credentials.', sorted_vol_snapshots[i]['SnapshotId'])
            logging.error(' Exception: %s', e)

# Copy volume snapshots from one region to another
def copy_snapshot(volume, src, dst):
    attempt_succeeded = False
    attempt_count = 0

    logging.info('    Looking for volume %s snapshots...', volume)
    vol_snapshots = get_volume_snapshots(volume)
    # Get last volume snapshot
    sorted_vol_snapshots = sorted(vol_snapshots, key=lambda k: k['StartTime'], reverse=True)
    snap_to_copy = sorted_vol_snapshots[0]['SnapshotId']
    logging.info('      The latest snapshot of volume %s to copy is %s.', volume, snap_to_copy)
    description = '[Copied %(snap_id)s from %(source)s] %(volume)s-%(date)s' % {
        'snap_id': snap_to_copy,
        'source': src,
        'volume': volume,
        'date': datetime.today().strftime('%d-%m-%Y')
    }
    # Try copy snapshot several times
    while attempt_count < 5 and not attempt_succeeded:
        try:
            # In order to copy snapshot we need to create connection to destination first
            dst_client = ec2_connect(ec2_region=dst)
            logging.info('    Copying snapshot %s from %s to %s...', snap_to_copy, src, dst)
            dst_snapshot = dst_client.copy_snapshot(
                SourceRegion=src,
                DestinationRegion=dst,
                SourceSnapshotId=snap_to_copy,
                Description=description
            )
            logging.info('    Snapshot %s created successfully.', dst_snapshot['SnapshotId'])
            attempt_succeeded = True
            try:
                logging.info('    Creating tags for snapshot %s.', dst_snapshot['SnapshotId'])
                dst_client.create_tags(
                    Resources=[dst_snapshot['SnapshotId']],
                    Tags=[{
                        'Key': 'Name',
                        'Value': volume
                }])
                logging.info('    Tags for snapshot %s created successfully.', dst_snapshot['SnapshotId'])
            except:
                logging.error('    Unable to create tags for snapshot %s', dst_snapshot['SnapshotId'])
        except botocore.exceptions.ClientError as e:
            logging.error('    Unable to copy snapshot %s from %s to %s. Please check your IAM credentials.', snap_to_copy, src, dst)
            logging.error('Exception: %s', e)
            time.sleep(wait_interval)
            attempt_count += 1


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='AWS Disaster Recovery script.')
    subparsers = parser.add_subparsers()

    create_parser = subparsers.add_parser('create', help='Create snapshots of attached volumes.')
    create_parser.set_defaults(func=create_snapshot)

    delete_parser = subparsers.add_parser('delete', help='Purge stale snapshots. Keep most recent (Default: 14).')
    delete_parser.add_argument('-k', '--keep', default=config['keep'], type=int, help='How many snapshots to keep.')
    delete_parser.add_argument('-r', '--region', default=get_instance_region(), type=str, help='Specify region containing snapshots to purge. (Default: current instance region)')
    delete_parser.set_defaults(func=purge_snapshot)

    copy_parser = subparsers.add_parser('copy', help='Copy latest volume snapshots or specific snapshot from one region to another.')
    copy_parser.add_argument('-s', '--src', type=str, default=get_instance_region(), help='The region from which to copy the snapshot. (Default: current instance region)')
    copy_parser.add_argument('-d', '--dst', type=str, default=config['backup_region'], help='The region to which to copy the snapshot. (Default: us-east-1)')
    copy_parser.set_defaults(func=copy_snapshot)

    args = parser.parse_args()
    logging.info('Started at %s with args %s', datetime.today().strftime('%d-%m-%Y %H:%M:%S'), args)
    client = ec2_connect(aws_access_key=aws_access_key, aws_secret_key=aws_secret_key, ec2_region=get_instance_region())
    volumes = get_instance_volumes(get_instance_id())

    if args.func == create_snapshot:
        logging.info('Creating snapshots...')
        for vol in volumes:
            create_snapshot(vol['Ebs']['VolumeId'])
        logging.info('Finished creating snapshots.')
    elif args.func == purge_snapshot:
        logging.info('Purging snapshots in {} region...'.format(args.region))
        for vol in volumes:
            purge_snapshot(volume=vol['Ebs']['VolumeId'], keep=args.keep, region=args.region)
        logging.info('Finished purging snapshots in region {}'.format(args.region))
    elif args.func == copy_snapshot:
        logging.info('Copying snapshots from {} to {} region...'.format(args.src, args.dst))
        for vol in volumes:
            copy_snapshot(volume=vol['Ebs']['VolumeId'], src=args.src, dst=args.dst)
        logging.info('Finished copying snapshots from {} to {} region.'.format(args.src, args.dst))
    else:
        logging.error('Unsupported arguments provided. Exit.')

    logging.info('Finished at %s', datetime.today().strftime('%d-%m-%Y %H:%M:%S'))

