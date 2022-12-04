#!/bin/sh


#
#    Raspberry Pi Backup System for Classrooms - Node Provisioning Script
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


# Change the following two lines to match your backup server
SERVER_IP='10.205.8.217'
SERVER_PORT=36888

### Do not change anything below this line ###

HOSTNAME_PATTERN='[A-Z0-9][A-Z0-9\-]*'

info() {
	printf '\033[1;34mInfo:\033[m ' >&2
	printf "$@" >&2
	printf '\n' >&2
}

warn() {
	printf '\033[1;33mWarning:\033[m ' >&2
	printf "$@" >&2
	printf '\n' >&2
}

err() {
	printf '\033[1;31mError:\033[m ' >&2
	printf "$@" >&2
	printf '\n' >&2
}

# Set new hostname given by user
change_hostname() {
	local response

	# Prompt user for new hostname
	# Read from/write to /dev/tty as stdin might be a pipe
	printf 'Enter a new hostname: ' > /dev/tty
	IFS='' read -r response < /dev/tty
	until
		printf '%s' "$response" | grep -ixq "$HOSTNAME_PATTERN"
	do
		err 'The hostname may only contain letters, numbers, and hyphens.'
		printf 'Enter a new hostname: ' > /dev/tty
		IFS='' read -r response < /dev/tty
	done

	info "Setting new hostname to '%s'." "$response"
	# Update /etc/hosts
	sed -i "/^127\.0\.[01]\.1\s\+$(hostname)\s*$/d" /etc/hosts
	printf '127.0.1.1\t%s\n' "$response" >> /etc/hosts
	# Set new hostname. Attempts to use hostnamectl(1) first. If that fails,
	# writes the new name to /etc/hostname then updates the live hostname using
	# hostname(1) or /proc/sys/kernel/hostname.
	if ! \
		hostnamectl --no-ask-password --static --pretty hostname "$response" \
			2>/dev/null
	then
		warn 'Calling hostnamectl(1) failed. Falling back to hostname(1).'
		printf '%s\n' "$response" > /etc/hostname
		if ! \
			hostname "$response" 2>/dev/null
		then
			warn 'Calling hostname(1) failed. Falling back to /proc/sys/kernel/hostname.'
			printf '%s' "$response" > /proc/sys/kernel/hostname
		fi
	fi
}

set -e

# Ensure we're running as root
if [ $(id -u) -ne 0 ]
then
	err 'This script must be run as root.'
	if [ -x "$0" ]
	then
		printf "\033[1;32mHint:\033[m Try running 'sudo %s'.\n" "$0" >&2
	fi
	exit 1
fi

# If the hostname has not been changed, prompt for a new one.
# If it appears to have been changed, print the detected hostname.
hostname="$(hostname)"
if [ "$hostname" = "raspberrypi" ]
then
	warn "You're using the default hostname '%s'." "$hostname"
	change_hostname
elif ! printf '%s' "$hostname" | grep -ixq "$HOSTNAME_PATTERN"
then
	warn 'Invalid or blank hostname detected.'
	change_hostname
fi

# Install required packages
info 'Downloading package information...'
info 'This may take a while.'
DEBIAN_FRONTEND=noninteractive apt-get -qq update
info 'Installing required packages...'
info 'This may take a while.'
DEBIAN_FRONTEND=noninteractive \
	apt-get -qq install --no-install-recommends \
	borgbackup openssh-client python3 python3-requests curl bash

info 'Creating systemd units...'
# Create systemd parent directories
install -d -m 755 \
	/usr/local/lib/systemd/system \
	/etc/systemd/system/backup.service.d \
	/etc/systemd/system/backup.timer.d

# Create backup service unit
umask 022
cat <<- 'EOF' > /usr/local/lib/systemd/system/backup.service
[Unit]
Description=Back up user files
Requires=network-online.target network.target
After=network-online.target network.target

[Service]
StateDirectory=backup_client
Type=oneshot
ExecStart=/usr/local/lib/backup_client.py
EOF

cat <<- 'EOF' > /etc/systemd/system/backup.service.d/00-triggers.conf
[Unit]
Before=shutdown.target
[Install]
WantedBy=shutdown.target
EOF

# Create backup timer unit
cat <<- 'EOF' > /usr/local/lib/systemd/system/backup.timer
[Unit]
Description=Timer for backup service

[Timer]
Unit=backup.service
OnCalendar=00:00
AccuracySec=15sec

[Install]
WantedBy=timers.target
EOF

echo '[Timer]' > /etc/systemd/system/backup.timer.d/00-times.conf

# Download SSH key
info 'Downloading & installing SSH key...'
umask 022
install -d -m 755 /usr/local/share/backup_client
curl -fsSL "http://$SERVER_IP:$SERVER_PORT/setup/node_key" \
	> /usr/local/share/backup_client/ssh_key

# Download client script
info 'Downloading & installing client script...'
install -d -m 755 /usr/local/lib
umask 027
curl -fsSL "http://$SERVER_IP:$SERVER_PORT/setup/client.py" \
	> /usr/local/lib/backup_client.py
chmod 750 /usr/local/lib/backup_client.py
umask 022

# Reload systemd and enable units
info 'Reloading systemd configuration...'
systemctl daemon-reload
info 'Enabling systemd units...'
systemctl enable backup.service backup.timer
info 'Running backup service...'
systemctl start backup.service
info 'Starting backup timer...'
systemctl start backup.timer

printf '\n'
info 'Done!'

exit 0
