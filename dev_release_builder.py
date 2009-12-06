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
        repos.append(line.split())
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


def find_head_github(user, repository):
    url = "http://github.com/api/v2/json/repos/show/%s/%s/branches" % (user, repository)
    response = urllib2.urlopen(url)
    info = json.loads(response.read())
    return info["branches"]["master"]


def download_tarball(user, repository, commit, show_progress=True):
    """
    Given a repository name and SHA1 download and store the tarball
    """
    basename = build_basename(user, repository, commit)
    filename = os.path.join(DATA_DIR, "%s.tar.gz" % basename)
    if not os.path.exists(filename):
        url = "http://github.com/%s/%s/tarball/%s" % (user, repository, commit)
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


def build_release(user, repository, commit):
    _run_setup_py = """import os, sys
__file__ = __SETUP_PY__
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
execfile(__file__)
"""
    basename = build_basename(user, repository, commit)
    source_dir = os.path.join(WORK_DIR, basename)
    setup_py = os.path.join(source_dir, "setup.py")
    script = _run_setup_py.replace("__SETUP_PY__", repr(setup_py))
    logger.indent += 2
    try:
        call_subprocess([sys.executable, "-c", script, "sdist"],
            show_stdout = False,
            command_desc = "python setup.py sdist"
        )
    finally:
        logger.indent -= 2


def run(data_dir, work_dir, repositories_file, completed_file):
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
        os.makedirs(work_dir)
    
    repositories = read_repositories(repositories_file)
    
    commits = []
    for kind, user, repository in repositories:
        if kind == "github":
            head = find_head_github(user, repository)
        commits.append((user, repository, head))
    
    completed = read_json_file(completed_file)
    completed_cache = dict([(c, True) for u, r, c in completed])
    
    try:
        for user, repository, commit in commits:
            current = "%s/%s (%s)" % (user, repository, commit[:7])
            
            if commit in completed_cache:
                logger.info("Skipping %s" % current)
                continue
            
            logger.info("Handling %s" % current)
            logger.indent += 2
            
            download_tarball(user, repository, commit)
            build_release(user, repository, commit)
            
            completed.append((user, repository, commit))
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
    
    run(data_dir, work_dir, repositories_file, completed_file)


if __name__ == "__main__":
    main()