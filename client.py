#!/usr/bin/env python3


#
#    Raspberry Pi Backup System for Classrooms - Client Script
#    Copyright (C) 2022  Kian Kasad
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License, version 3, as
#    published by the Free Software Foundation.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#


import atexit
import json
import os
import pwd
import requests
import shutil
import socket
import subprocess
import sys
import tempfile

from json import JSONDecodeError
from pathlib import Path
from requests.exceptions import HTTPError
from stat import S_IRUSR, S_IWUSR, S_IXUSR
from subprocess import CalledProcessError


# Default IP address of the backup server if one is not provided in the stored
# configuration data
DEFAULT_SERVER_IP = '10.205.8.217'

# Port on which the backup server is serving configuration
CONFIG_SERVER_PORT = 36888

# Port on which the backup server is listening for SSH connections
SSHD_PORT = 22

# Location of drop-in configuration file for backup.timer
TIMER_DROPIN_PATH = '/etc/systemd/system/backup.timer.d/00-times.conf'

# Location of drop-in configuration file for backup.service
SERVICE_DROPIN_PATH = '/etc/systemd/system/backup.service.d/00-triggers.conf'

# Command to use instead of 'ssh'
rsh = 'ssh -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
SSH_KEY = '/usr/local/share/backup_client/ssh_key'

# Environment variables to run Borg with
BORG_ENV = {
    'BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK': 'yes',
    'BORG_RELOCATED_REPO_ACCESS_IS_OK': 'yes',
}

# Empty configuration structure.
# Must contain all the keys that might be accessed but need not contain any
# values.
DEFAULT_CONFIG = {
    'epoch': 0,
    'server': {
        'host': DEFAULT_SERVER_IP,
        'httpd_port': CONFIG_SERVER_PORT,
        'sshd_port': SSHD_PORT,
    },
    'updates': [
        {
            'epoch': 0,
            'script': 'updates/00-no_op.sh',
        }
    ],
    'archive_name_format': '{now}',
    'backup_times': [
        '@before:shutdown.target'
    ],
    'backup_time_randomized_delay': '2min',
    'backup_paths': ['~/Desktop'],
    'backup_user': 'pi',
}


def die(*args, **kwargs):
    if args:
        error(*args, **kwargs)
    print('Exiting...')
    exit(1)


def log(*args, **kwargs):
    print('\x1b[1;34mInfo:\x1b[m ', end='')
    print(*args, **kwargs)


def warn(*args, **kwargs):
    print('\x1b[1;33mWarning:\x1b[m ', end='')
    print(*args, **kwargs)


def error(*args, **kwargs):
    print("\x1b[1;31mError:\x1b[m ", end='')
    print(*args, **kwargs)


def fill_struct_with_defaults(source, default):
    for key, value in default.items():
        if key not in source:
            source[key] = value
        elif isinstance(source[key], dict):
            fill_struct_with_defaults(source[key], value)
        elif isinstance(source[key], str) and not source[key]:
            source[key] = value


def apply_config(config, prev_config):
    # Apply updates from updates list
    current_update_epoch = max(
        [update['epoch'] for update in prev_config['updates']]
    )
    latest_update_epoch = max(
        [update['epoch'] for update in config['updates']]
    )
    for i in range(current_update_epoch + 1, latest_update_epoch + 1):
        try:
            update = [update for update in config['updates']
                      if update['epoch'] == i][0]
            apply_update(config['server'], i, update['script'])
        except IndexError:
            pass

    # Set times for backup.timer
    # See systemd.timer(5) and systemd.time(7) for details
    trigger_times = []
    try:
        with open(TIMER_DROPIN_PATH, 'w') as times:
            print('[Timer]', 'OnCalendar=', sep='\n', file=times)
            # Print randomized delay setting
            # TODO: check validity using systemd-analyze
            print('RandomizedDelaySec=',
                  config['backup_time_randomized_delay'], file=times)

            # Print times
            for time in config['backup_times']:
                if time.startswith('@'):
                    entry = time.split(':')
                    if len(entry) < 2:
                        entry.append('')
                    trigger_times.append(entry)
                else:
                    # TODO: check validity using systemd-analyze(1)
                    print('OnCalendar=', time, sep='', file=times)
    except OSError as err:
        die('Failed to save trigger times to ',
            TIMER_DROPIN_PATH, ': ', err, sep='')

    # Set triggers for backup.service
    # See systemd.service(5) and systemd.unit(5) for details
    if trigger_times:
        unit_entries = []
        install_entries = []
        for order, unit in trigger_times:
            if order == '@before':
                unit_entries.append('Before=' + unit)
            elif order == '@after':
                unit_entries.append('After=' + unit)
            else:
                warn(f"Ignoring invalid trigger entry: '@{order}:{unit}'")
                continue
            install_entries.append('WantedBy=' + unit)
        try:
            with open(SERVICE_DROPIN_PATH, 'w') as dropin:
                print('[Unit]', file=dropin)
                for entry in unit_entries:
                    print(entry, file=dropin)
                print('[Install]', 'WantedBy=', sep='\n', file=dropin)
                for entry in install_entries:
                    print(entry, file=dropin)
        except OSError as err:
            die('Failed to save triggers to ',
                SERVICE_DROPIN_PATH, ': ', err, sep='')

    # Reload systemd
    try:
        cmd = ['/usr/bin/systemctl', '--no-ask-password']
        subprocess.run(cmd, check=True)
    except CalledProcessError as err:
        warn('Failed to reload systemd. Continuing anyways...')


def apply_update(server, epoch, script_name):
    log('Attempting to apply update #', epoch, '...', sep='')
    uri = f"http://{server['host']}:{server['httpd_port']}/{script_name}"
    try:
        response = requests.get(uri)
        script = response.text
        status = subprocess.run(
            '/bin/bash', input=script, text=True, check=True)
    except CalledProcessError as err:
        die(f"Update #{epoch}'s script returned non-zero exit status {err.returncode}")
    except ConnectionError as err:
        die(f'Failed to download script for update #{epoch}:', err)
    except HTTPError as err:
        die('HTTP error:', err)


def store_config(data, path):
    try:
        with open(path, 'w') as file:
            file.write(data)
    except OSError as err:
        warn('Failed to save updated configuration:', err)


def do_backup(config, ssh_key, is_retry=False):
    global rsh, BORG_ENV

    server_ip = config['server']['host']
    sshd_port = config['server']['sshd_port']

    repo_uri = f'ssh://backup@{server_ip}:{sshd_port}/~/repos/' + '{hostname}'
    archive_path = repo_uri + '::' + config['archive_name_format']

    cmd = [
        '/usr/bin/borg',
        '--rsh', rsh,
        'create',
        '--log-json',
        '--json',
        archive_path,
        *[os.path.expanduser(path) for path in config['backup_paths']]
    ]

    # Run Borg
    proc = subprocess.run(cmd, env=BORG_ENV, capture_output=True, text=True)

    # Process log messages
    repo_doesnt_exist = False
    errors = []
    warnings = []
    for line in proc.stderr.splitlines():
        try:
            msg = json.loads(line)
        except JSONDecodeError:
            continue  # ignore non-JSON output
        if msg['levelname'] == 'ERROR':
            if msg.get('msgid', '') == 'Repository.DoesNotExist':
                repo_doesnt_exist = True
            errors.append(msg)
        elif msg['levelname'] == 'WARNING':
            warnings.append(msg)

    if proc.returncode == 0:
        # Succeeded
        log('Borg successfully created backup.')
    elif proc.returncode == 1:
        # Succeeded with warnings
        warn('Borg successfully created backup, but produced',
             len(warnings), 'warnings (listed below).')
        for msg in warnings:
            warn('borg:', msg['message'])
    elif proc.returncode == 2:
        # Failed
        if repo_doesnt_exist and not is_retry:
            warn('Backup repository does not exist. Creating new repository...')
            create_repo(repo_uri, ssh_key)
            do_backup(config, ssh_key, True)
        else:
            error('Borg failed to create backup and produced',
                  len(errors), 'errors and', len(warnings), 'warnings (listed below).')
            for msg in errors:
                error('borg:', msg['message'])
            for msg in warnings:
                warn('borg:', msg['message'])
            die()


def create_repo(uri, ssh_key):
    global rsh, BORG_ENV
    cmd = [
        '/usr/bin/borg',
        '--rsh', rsh,
        'init',
        '--log-json',
        '--encryption', 'none',
        uri
    ]

    # Run Borg
    proc = subprocess.run(cmd, env=BORG_ENV, capture_output=True, text=True)

    # Process log messages
    errors = []
    warnings = []
    for line in proc.stderr.splitlines():
        try:
            msg = json.loads(line)
        except JSONDecodeError:
            continue  # ignore non-JSON output
        if msg['levelname'] == 'ERROR':
            errors.append(msg)
        elif msg['levelname'] == 'WARNING':
            warnings.append(msg)

    # Check return code
    if proc.returncode == 0:
        # Success
        log('Successfully created repository at', uri)
    elif proc.returncode == 1:
        warn('Successfully created repository at', uri,
             'but Borg produced', len(warnings), warnings)
        for msg in warnings:
            warn('borg:', msg['message'])
    elif proc.returncode == 2:
        # Failed
        error('Borg failed to create repository and produced',
              len(warnings), 'warnings and', len(errors), 'errors (listed below).')
        for msg in warnings:
            error('borg:', msg['message'])
        for msg in errors:
            warn('borg:', msg['message'])
        die()


# Make a user-readable copy of the SSH key
def copy_ssh_key(uid, gid):
    try:
        # Create temporary key file
        (fd, tmppath) = tempfile.mkstemp()
        os.chown(fd, uid, gid)
        os.chmod(fd, S_IRUSR)

        # Delete temporary key file when program exits
        def delete_ssh_key(ssh_key):
            try:
                os.remove(ssh_key)
            except Exception as err:
                pass  # ignore
        atexit.register(delete_ssh_key, tmppath)

        # Copy contents from original key
        with open(SSH_KEY, 'rb') as src:
            with open(fd, 'wb') as dst:
                shutil.copyfileobj(src, dst)
    except Exception as err:
        die('Failed to make copy of SSH key:', err)

    return tmppath


def get_drop_ids(user):
    try:
        if isinstance(user, int):
            uid = user
            gid = pwd.getpwuid(uid).pw_gid
        else:
            pwinfo = pwd.getpwnam(user)
            uid = pwinfo.pw_uid
            gid = pwinfo.pw_gid
    except KeyError as err:
        die('Failed to get UID/GID of target user:', err)
    return (uid, gid)


def drop_privileges_to(uid, gid):
    try:
        # Order is important
        os.environ.clear()
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
        os.umask(0o022)
        os.chdir(Path.home())
    except Exception as err:
        die('Failed to drop privileges:', err)


def main():
    global DEFAULT_CONFIG, rsh

    # Attempt to load stored configuration file
    try:
        state_dir = Path(os.getenv('STATE_DIRECTORY').split(':')[0])
    except:
        die("Environment variable STATE_DIRECTORY is not set")
    stored_config_path = state_dir / 'config.json'
    try:
        with open(stored_config_path, 'r') as file:
            stored_config = json.load(file)
            fill_struct_with_defaults(stored_config, DEFAULT_CONFIG)
    except FileNotFoundError:
        warn('No stored configuration file found.')
        stored_config = DEFAULT_CONFIG
    except ValueError:
        warn('Stored configuration contains invalid JSON. Ignoring it.')
        stored_config = DEFAULT_CONFIG

    # Find backup server parameters
    server_host = stored_config['server']['host']
    httpd_port = stored_config['server']['httpd_port']
    log('Backup server host:', server_host)
    log('HTTPd port:', httpd_port)

    # Fetch latest configuration from server
    uri = f'http://{server_host}:{httpd_port}/config.json'
    try:
        response = requests.get(uri)
        response.raise_for_status()
        config_json = response.text
        config = response.json()
        fill_struct_with_defaults(config, DEFAULT_CONFIG)
    except ConnectionError as err:
        die('Connection to configuration server failed:', err)
    except HTTPError as err:
        die('HTTP error:', err)
    except ValueError as err:
        die('Invalid JSON response from configuration server:', err)

    # If fetched config is newer, apply and store it
    if config['epoch'] > stored_config['epoch']:
        apply_config(config, stored_config)
        store_config(config_json, stored_config_path)

    uid, gid = get_drop_ids(os.getenv('BACKUP_USER')
                            or config['backup_user'] or 'pi')
    ssh_key = copy_ssh_key(uid, gid)
    rsh += ' -i ' + ssh_key
    drop_privileges_to(uid, gid)
    do_backup(config, ssh_key)


if __name__ == '__main__':
    main()
