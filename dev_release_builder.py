import os
import tarfile
import shutil
import sys
import urllib2

try:
    import simplejson as json
except ImportError:
    import json

import pip
# @@@ fix me
try:
    from pip.log import Logger
except ImportError:
    from pip import Logger
from pip import call_subprocess


logger = Logger([(1, sys.stdout)])
pip.logger = logger


REPOSITORIES_FILE = os.path.join(os.path.dirname(__file__), "repositories.txt")
COMPLETED_FILE = os.path.join(os.path.dirname(__file__), "completed")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
WORK_DIR = os.path.join(DATA_DIR, "work")
DIST_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "dist"))


def format_size(bytes):
    if bytes > 1000*1000:
        return "%.1fMb" % (bytes/1000.0/1000)
    elif bytes > 10*1000:
        return "%iKb" % (bytes/1000)
    elif bytes > 1000:
        return "%.1fKb" % (bytes/1000.0)
    else:
        return "%ibytes" % bytes


def build_basename(user, repository, commit):
    return "%s-%s-%s" % (user, repository, commit[:7])


def read_repositories(filename):
    repos = []
    for line in open(filename, "rb"):
        bits = line.split()
        if len(bits) == 3:
            kind, user, repository = bits
            branch = None
        elif len(bits) == 4:
            kind, user, repository, branch = bits
        else:
            raise Exception("incompatible file format for '%s'" % filename)
        repos.append((kind, user, repository, branch))
    return repos


def read_json_file(filename):
    if not os.path.exists(filename):
        return []
    items = []
    for line in open(filename, "rb"):
        items.append(json.loads(line))
    return items


def dump_json_items(filename, items):
    fp = open(filename, "wb")
    for item in items:
        fp.write("%s\n" % json.dumps(item))
    fp.close()


def find_head_github(user, repository, branch=None):
    if branch is None:
        branch = "master"
    url = "http://github.com/api/v2/json/repos/show/%s/%s/branches" % (user, repository)
    response = urllib2.urlopen(url)
    info = json.loads(response.read())
    return info["branches"][branch]


def download_tarball(kind, user, repository, commit, show_progress=True):
    """
    Given a repository name and SHA1 download and store the tarball
    """
    basename = build_basename(user, repository, commit)
    filename = os.path.join(DATA_DIR, "%s.tar.gz" % basename)
    # force bitbucket to always download
    if not os.path.exists(filename) or kind == "bitbucket":
        if kind == "github":
            url = "http://github.com/%s/%s/tarball/%s" % (user, repository, commit)
        elif kind == "bitbucket":
            url = "http://bitbucket.org/%s/%s/get/%s.tar.gz" % (user, repository, commit)
        response = urllib2.urlopen(url)
        try:
            total_length = int(response.info()["content-length"])
        except (ValueError, KeyError):
            total_length = 0
        logger.info("Fetching %s" % url)
        logger.indent += 2
        downloaded = 0
        fp = open(filename, "wb")
        try:
            if show_progress:
                if total_length:
                    logger.start_progress("Downloading tarball (%s): " % format_size(total_length))
                else:
                    logger.start_progress("Downloading tarball (unknown size): ")
            else:
                logger.info("Downloading")
            while 1:
                chunk = response.read(4096)
                if not chunk:
                    break
                downloaded += len(chunk)
                if show_progress:
                    if not total_length:
                        logger.show_progress("%s" % format_size(downloaded))
                    else:
                        logger.show_progress("%3i%%  %s" % (100*downloaded/total_length, format_size(downloaded)))
                fp.write(chunk)
            fp.close()
        finally:
            if show_progress:
                logger.end_progress("%s downloaded" % format_size(downloaded))
            logger.indent -= 2
    logger.info("Extracting %s" % os.path.basename(filename))
    tar = tarfile.open(filename)
    tar.extractall(path=WORK_DIR)


def build_release(dist_dir, kind, user, repository, commit):
    basename = build_basename(user, repository, commit)
    if kind == "github":
        source_dir = os.path.join(WORK_DIR, basename)
    elif kind == "bitbucket":
        source_dir = os.path.join(WORK_DIR, repository)
    setup_py = os.path.realpath(os.path.join(source_dir, "setup.py"))
    # use setuptools hack to allow egg_info in setup.cfg to work for
    # development builds (requires setuptools in dev release environment)
    cmd = [
        sys.executable,
        "-c", "import setuptools;__file__=%r;execfile(%r)" % (setup_py, setup_py),
        "sdist",
        "-d", dist_dir,
    ]
    call_subprocess(cmd,
        cwd = source_dir,
        show_stdout = False,
        command_desc = "python setup.py sdist",
    )


def run(data_dir, work_dir, repositories_file, completed_file, dist_dir):
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
        os.makedirs(work_dir)
    
    repositories = read_repositories(repositories_file)
    
    commits = []
    for kind, user, repository, branch in repositories:
        if kind == "github":
            head = find_head_github(user, repository, branch)
        elif kind == "bitbucket":
            # tip file download is the only way to get the latest from what
            # i can tell
            head = "tip"
        else:
            logger.warning("Unknown service")
            continue
        commits.append((kind, user, repository, head))
    
    completed = read_json_file(completed_file)
    completed_cache = dict([(c, True) for k, u, r, c in completed])
    
    try:
        for kind, user, repository, commit in commits:
            current = "%s/%s (%s)" % (user, repository, commit[:7])
            
            if commit in completed_cache:
                logger.info("Skipping %s" % current)
                continue
            
            logger.info("Handling %s" % current)
            logger.indent += 2
            
            download_tarball(kind, user, repository, commit)
            build_release(dist_dir, kind, user, repository, commit)
            
            # only non-bitbucket items get to be marked completed as they
            # have a distinct commit we can ensure is completed
            if not kind == "bitbucket":
                completed.append((kind, user, repository, commit))
            logger.indent -= 2
    finally:
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)
        dump_json_items(completed_file, completed)


def main():
    
    # @@@ optparse
    data_dir = DATA_DIR
    work_dir = WORK_DIR
    repositories_file = REPOSITORIES_FILE
    completed_file = COMPLETED_FILE
    dist_dir = DIST_DIR
    
    run(data_dir, work_dir, repositories_file, completed_file, dist_dir)


if __name__ == "__main__":
    main()