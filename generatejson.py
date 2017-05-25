#!/usr/bin/python
# -*- coding: utf-8 -*-

# Generate Json file for installapplications
# Usage: python generatejson.py --rootdir /path/to/rootdir
#
# --rootdir path is the directory that contains each stage's pkgs directory
# As of InstallApplications 5/13/17, the directories must be named (lowercase):
#   'prestage', 'stage1', and 'stage3'
#
# The generated Json will be saved in the root directory
# Future plan for this tool is to add AWS S3 integration for auto-upload

import argparse
import hashlib
import json
import optparse
import os
import sys

iapath = "/private/tmp/installapplications/"
bsname = "bootstrap.json"


def gethash(filename):
    # This code borrowed from InstallApplications.py, thanks Erik
    hash_function = hashlib.sha256()
    if not os.path.isfile(filename):
        return 'NOT A FILE'

    fileref = open(filename, 'rb')
    while 1:
        chunk = fileref.read(2**16)
        if not chunk:
            break
        hash_function.update(chunk)
    fileref.close()
    return hash_function.hexdigest()


def s3upload(s3, filepath, bucket, filename, mime="application/octetstream"):
    s3.upload_file(filepath, bucket, filename,
                   ExtraArgs={'ACL': 'public-read', 'ContentType': mime})
    s3url = s3.generate_presigned_url(
                   ClientMethod='get_object',
                   Params={
                        'Bucket': bucket,
                        'Key': filename
                   })
    url = s3url.split("?", 1)[0]
    print "Uploaded %s to %s" % (filename, bucket)
    return url


def main():
    usage = '%prog --rootdir /path/to/dir/ [options]'
    op = optparse.OptionParser(usage=usage)
    op.add_option('--rootdir', help=(
        'Required: Root directory path for InstallApplications stages'))
    op.add_option('--s3', action="store_true", help=(
        'Optional: Enable S3 upload'))
    op.add_option('--awsaccesskey', default=None, help=(
        'Set AWS Access Key. Requires S3 option'))
    op.add_option('--awssecretkey', default=None, help=(
        'Set AWS Secret Access Key. Requires S3 option'))
    op.add_option('--s3region', default=None, help=(
        'Set S3 region (e.g. us-east-2). Requires S3 option'))
    op.add_option('--s3bucket', default=None, help=(
        'Set S3 bucket name. Requires S3 option'))
    opts, args = op.parse_args()

    if opts.rootdir and not opts.s3:
        rootdir = opts.rootdir
        uploadtos3 = False
    elif opts.rootdir and opts.s3:
        rootdir = opts.rootdir

        if not opts.awsaccesskey:
            print "Please provide an AWS Access Key with --awsaccesskey"
            sys.exit(1)
        if not opts.awssecretkey:
            print "Please provide an AWS Secret Access Key with --awssecretkey"
            sys.exit(1)
        if not opts.s3region:
            print "Please provide a S3 Region (e.g. us-east-2) with --s3region"
            sys.exit(1)
        if not opts.s3bucket:
            print "Please provide a S3 Bucket name with --s3bucket"
            sys.exit(1)

        try:
            import boto3
        except ImportError:
            print "Please install Boto3 (pip install boto3)"
            sys.exit(1)

        s3 = boto3.client('s3', region_name=opts.s3region,
                          aws_access_key_id=opts.awsaccesskey,
                          aws_secret_access_key=opts.awssecretkey)
        uploadtos3 = True
    else:
        op.print_help()
        sys.exit(1)

    # Traverse through root dir, find all stages and all pkgs to generate json
    stages = {}
    for subdir, dirs, files in os.walk(rootdir):
        for d in dirs:
            stages[str(d)] = []
        for file in files:
            if file.endswith('.pkg'):
                filepath = os.path.join(subdir, file)
                filename = os.path.basename(filepath)
                filehash = gethash(filepath)
                filestage = os.path.basename(os.path.abspath(
                            os.path.join(filepath, os.pardir)))
                if uploadtos3:
                    fileurl = s3upload(s3, filepath, opts.s3bucket, filename)
                    filejson = {"file": iapath + filename, "url": fileurl,
                                "hash:": str(filehash)}
                else:
                    filejson = {"file": iapath + filename, "url": "",
                                "hash:": str(filehash)}

                stages[filestage].append(filejson)

    # Saving the bootstrap json in the root dir
    bspath = os.path.join(rootdir, bsname)
    with open(bspath, 'w') as outfile:
        json.dump(stages, outfile, sort_keys=True, indent=2)

    print "Json saved to root directory"

    if uploadtos3:
        bsurl = s3upload(s3, bspath, opts.s3bucket, bsname, "application/json")
        print "Json URL for InstallApplications is %s  " % bsurl


if __name__ == '__main__':
    main()
