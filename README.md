# Raspberry Pi Backup System for Classrooms

Note: This README is generated from the original article located at <https://kasad.notion.site/Raspberry-Pi-Backup-System-599ef1eacbc44781ae3d198d03363775>.
Content may be outdated or improperly formatted. See the original instead.

## Abstract

### Problem

Students’ files on Raspberry Pi’s are being modified or deleted by other students without their permission or knowledge.

### Solution

The most practical solution is to create a system in which every Raspberry Pi will back up a predetermined set of files to a central location at configurable times.

#### Goals

1. Automatic; no manual interaction is required to perform backups.
2. Scalable; adding new Pi’s to the system is easy.
3. Independent; no outside infrastructure or services are needed.
4. Frequent; in a classroom setting, work may be updated on an hourly basis. Backups must reflect these frequent changes.
5. Easy to index; backups are only useful if they can be restored. It must be easy to index backups based on the node and time at which they were archived.
6. Centrally configurable; the files to be backed up, backup schedule, server location, and any other configuration variables must be controlled from one central location.
    1. The system must also include a method to automatically update the client software on all nodes from one central location.
7. Discreet; the backup system must not impact students’ ability to use the Raspberry Pi’s. Preferably, it will be completely unnoticeable.

### Threat model

Nodes can be controlled by a malicious user. They could even gain root access to the node. We assume that the user of the node, even a malicious one, has limited technical knowledge and thus will not be capable of finding/modifying the backup system’s configuration or execution.

The backup server is assumed to be secure and protected. This cannot be the case when using one of the nodes as the backup server, so that method is not recommended.

## Implementation

In order to meet the goals listed above, we’ll build the system using [Borg Backup](https://borgbackup.org), which is an archive/backup software that is highly customizable and efficient.

The backup system is made of several parts:

1. The backup server
2. Several Raspberry Pi “nodes”
3. A network

### Borg usage

#### **Repositories**

The Borg documentation discourages backing up many clients to the same server repository because it causes problems with deduplication. Also, while Borg can accept backups from multiple different clients to one repository, it cannot do so simultaneously. Therefore the best approach is for each node to have its own repository on the backup server. This requires that each node have a unique identifier¹ and that the backup script is capable of creating a repository on the server if one does not already exist.

¹ This unique identifier can be a hardware-determined value (e.g. MAC address) or a user-specified value (e.g. hostname). In the latter case, they must be manually verified to ensure they do not collide.

#### **Encryption/Authentication**

Borg supports encrypting the contents of backups. We don’t need to use this, as we assume that the backup server is a secure environment.

Borg also supports restricting access to repositories using keys and passwords. We do want to enable this, as any node could access any other node’s backups if they are unprotected. Unfortunately, it isn’t possible to give each node’s repository a unique password while keeping the system scalable, so we will choose one password which all repositories share. This will be stored in a read-protected file on the node. However, since the node can be completely controlled by a malicious user, this does not prevent the password from being read; it only keeps it safe from non-technical users. Luckily, this is the vast majority of the expected user base.

#### Transport

We will use SSH as the transport, with SSH keys for authentication. By using keys, we can limit the node’s capabilities on the server to just performing backups. To keep the system scalable, we must choose one of the following methods:

1. Each node has its own private key which is granted access to its repository only.
2. All nodes share the same key, which has append-only access² to all repositories on the server.

Option 1 would not be scalable without writing an additional automated key management program, so we will choose Option 2.

² Read Borg’s [documentation on append-only access](https://borgbackup.readthedocs.io/en/stable/usage/notes.html#append-only-mode-forbid-compaction). It does not prevent deletion of backups. It only makes such deletions manually reversible if handled carefully.

### Backup server

The backup server will handle receiving backups from nodes as well as serving configuration data. It may also prune backups at configurable time intervals. The next few sections will cover the process to set up a backup server.

#### Receiving backups

This aspect is quite simple, as no action needs to be taken on the server side once Borg is installed and the underlying transport mechanism, namely SSH, is properly configured.

The initial setup consists of the following three steps:

- ************************Install packages************************
    
    We need to install Borg and the OpenSSH server:
    
    ```bash
     apt install borgbackup openssh-server
    ```
    
- **Create the `backup` user**
    
    We want to isolate the backup server’s process from the default user, especially if the backup server is one of the nodes. To do this, we’ll create a new system user called `backup` with its home directory set to `/var/backups`:³
    
    ```bash
    useradd -r -m -d /var/backups -c 'Backup custodian' -s /bin/bash backup
    ```
    
    On Debian, the `backup` user exists by default. It isn’t used by anything, though, so run the following command to delete the user, then run the command above again.
    
    ```bash
    userdel -r -f backup
    ```
    
    A password should be set for the new user to prevent unauthorized logins via SSH. Alternatively SSH password authentication can (and should) be disabled.
    
    ³ The user can be named anything else so long as you use the right name in the rest of the system.
    
- ******************************Configure SSH******************************
    
    SSH is the underlying transport that Borg uses. It handles connecting to the backup server, authenticating, connection encryption, etc.
    
    We need to do the following to set up SSH for our use:
    
    1. Modify the SSH server’s configuration
    2. Enable the SSH server
    3. Create an SSH key for the nodes to authenticate with
    4. Set access permissions for the new SSH key
    
    Before the SSH server is enabled, ensure that `/etc/ssh/sshd_config` contains the following:
    
    ```
    Port 22
    AddressFamily any
    ListenAddress 0.0.0.0
    ListenAddress ::
    
    HostKey /etc/ssh/ssh_host_rsa_key
    HostKey /etc/ssh/ssh_host_ecdsa_key
    HostKey /etc/ssh/ssh_host_ed25519_key
    
    PermitRootLogin no
    StrictModes yes
    
    PubkeyAuthentication yes
    AuthorizedKeysFile .ssh/authorized_keys
    ```
    
    To disable password authentication for the `backup` user (highly recommended), add the following block at the end of the file:
    
    ```
    Match User backup
        PasswordAuthentication no
    ```
    
    To enable the SSH server, run the following two commands. Alternatively, `raspi-config` can be used.
    
    ```bash
    ssh-keygen -A                        # Regenerate SSH host keys
    systemctl enable --now ssh.service   # Enable the SystemD service for SSH
    ```
    
    Now, login as the backup custodian (i.e. the `backup` user). This can be done by logging in to the desktop as the backup custodian, or by starting a shell running as the `backup` user:
    
    ```bash
    sudo -i -u backup
    ```
    
    All of the following commands in this section must be run as the backup custodian.
    
    As the backup custodian, run the following command to generate an SSH key pair. This will create two files, `node_key` and `node_key.pub`. The former is the “private” key, i.e. the one that will grant a user access to the backup server. The latter is the “public” key.
    
    ```bash
    ssh-keygen -t ed25519 -N '' -C 'Node backup key' -f node_key
    ```
    
    Don’t give the key a password. Just press Enter at the password prompts.
    
    Next, we need to allow nodes to log in using this key and set the proper restrictions.
    
    ```bash
    umask 077
    mkdir -vp ~/.ssh ~/repos
    cat << EOF >> ~/.ssh/authorized_keys
    command="/usr/bin/borg serve --append-only --restrict-to-path ~/repos",restrict $(cat ~/node_key.pub)
    EOF
    ```
    
    This creates the file `~/.ssh/authorized_keys` as the backup custodian and adds an entry to it which authorizes the node key we created to log in,⁴ with the restriction that the only thing it can do is access a Borg repository in the `repos` folder in append-only mode. We also created the `~/repos` directory, which is where the Borg backup repositories will live.
    
    ⁴ It does this by copying the content of the public key `node_key.pub` into the `authorized_keys` file after the settings to restrict access.
    

Once the above steps have been completed, the backup server is ready to receive backups. Optionally, follow the steps below to test it:

- ****************Testing the backup server****************
    
    First, copy the `node_key` file to the device from which you want to test the backup server. This can be the backup server itself, but ideally it would be one of the nodes. The remaining steps will assume it is one of the nodes and will refer to it as such.
    
    Next, install Borg on the node. Use the same command we used to install Borg on the server.
    
    Finally, create an unencrypted, unauthenticated test repository on the server. This requires knowing the server’s IP address:
    
    ```bash
    borg init --encryption none backup@$SERVER_IP:repos/TEST
    ```
    
    Then create a test backup:
    
    ```bash
    echo 'This is a test' > /tmp/backup_test.txt
    borg create --stats --compression zstd backup@$SERVER_IP:repos/TEST::t1 /tmp/backup_test.txt
    rm /tmp/backup_test.txt
    ```
    
    This should succeed. Next, we’ll attempt to delete the backup archive.
    
    ```bash
    borg delete --stats backup@$SERVER_IP:repos/TEST::t1
    ```
    
    This should also succeed. However, no data will actually be deleted from the repository. It will simply mark the backup archive as deleted. [See (2) for details](https://www.notion.so/Raspberry-Pi-Backup-System-599ef1eacbc44781ae3d198d03363775).
    

#### Serving configuration

In order to achieve the system’s goals of being both automatic and configurable, we need a central configuration server. This will store the configuration in one place (e.g. one JSON file). Each node will then request the configuration from the server each time it performs a backup.

This configuration server will also allow us to deploy updates to all the nodes in the system.

The configuration data can be served over many protocols and in many formats. We’ll use JSON over HTTP because both are ubiquitous and easy to use. To avoid clashing with any other HTTP services, we’ll serve the data on TCP port 36888.

For the HTTP server, we’ll use [webfs](https://linux.bytesex.org/misc/webfs.html) because it’s small, simple, lightweight, and has a Debian package available. We’ll also use [jq](https://stedolan.github.io/jq) to parse the JSON data.

The setup for the configuration server consists of the following steps:

- **Install required packages**
    
    Install `webfs` :
    
    ```bash
    apt install webfs
    ```
    
- **Create a systemd service**
    
    In order for our configuration server to be useful, we need it to run in the background automatically. The easiest way to do this on a Raspberry Pi (or any Debian device) is by creating a [systemd](https://systemd.io) service. Systemd, the service manager, will automatically start our HTTP server when the backup server boots.
    
    To create the service, create the file `/usr/local/lib/systemd/system/backup-conf-httpd.service` with the following contents. This will require root privileges and may require creating the parent directory `/usr/local/lib/systemd/system` first.
    
    ```ini
    [Unit]
    Description=Configuration server for Raspberry Pi backup system
    Documentation=man:webfsd(1)
    Requires=network.target
    After=network.target
    
    [Service]
    User=backup
    Group=backup
    WorkingDirectory=~
    EnvironmentFile=/var/backups/config/config_server_settings.env
    ExecStart=/usr/bin/webfsd -F -j -c 50 -p ${PORT} -R ${CONFIG_SERVER_DATA_ROOT}
    Type=exec
    AmbientCapabilities=CAP_SYS_CHROOT
    CapabilityBoundingSet=CAP_SYS_CHROOT
    
    [Install]
    WantedBy=default.target
    Alias=backup-config-server.service
    ```
    
    This service file will run the `webfsd` HTTP server, using environment variables defined in the file `config/config_server_settings.env` within the backup custodian’s home directory.
    
- **Create the configuration server’s settings file**
    
    Run the following commands as the backup custodian to create the file needed by the systemd service for the configuration server.
    
    ```bash
    mkdir -vp ~/config
    cat << 'EOF' > ~/config/config_server_settings.env
    # Set the port on which the HTTP server will serve content
    PORT=36888
    
    # Set the directory that the HTTP will serve files from.
    # Only files in this directory will be accessible via the
    # configuration server.
    CONFIG_SERVER_DATA_ROOT=/var/backups/.conf_server_data
    EOF
    ```
    
- **************************************************Create the configuration data directory**************************************************
    
    The configuration data directory, `.conf_server_data/` will contain a **symbolic link**, which is a file that points to another file. This way, we can serve the file `config/config.json` without also serving the rest of the files in the `config/` directory.
    
    The configuration server will also serve update scripts. These will be served from `.conf_server_data/updates`. However, we want to store the update scripts in `updates/`, so we’ll make another link in the data directory for this.
    
    To create the directory and links, run the following commands as the backup custodian.
    
    ```bash
    mkdir -vp ~/.conf_server_data
    ln -vs ~/config/config.json ~/.conf_server_data/config.json
    ln -vs ~/updates ~/.conf_server_data/updates
    ```
    
    *Note: it doesn’t matter that the files we’re linking to don’t exist yet.*
    
    And since we haven’t done it yet, let’s create the `updates/` directory and a no-op update script.
    
    ```bash
    mkdir -vp ~/updates
    cat << EOF > ~/updates/00-no_op.sh
    #!/bin/sh
    exit
    EOF
    ```
    
- **Create the configuration file**
    
    Finally, we need to create the file which contains the configuration data we’ll be serving. To do this, create the file `config/config.json` as the backup custodian and give it the following contents.
    
    ```json
    {
    	"epoch": 1,
    
    	"server": {
    		"host": "",
    		"httpd_port": 36888,
    		"sshd_port": 22
    	},
    
    	"updates": [
    		{
    			"epoch": 0,
    			"script": "updates/00-no_op.sh"
    		}
    	],
    
    	"archive_name_format": "{now}",
    
    	"backup_times": [
    		"@before:shutdown.target",
    		"Mon,Tue,Thu,Fri 10:00",
    		"Mon,Tue,Thu,Fri 11:50",
    		"Mon,Tue,Thu,Fri 14:30",
    		"Wed 10:00",
    		"Wed 11:50",
    		"Wed 14:00"
    	],
    	"backup_time_window_length_in_minutes": 2,
    
    	"backup_paths": [
    		"/home/pi/Desktop"
    	]
    }
    ```
    
    The contents of the configuration file will be discussed in a later section. That being said, it’s fairly easy to understand, with the exception of possibly the `updates` and `epoch` directives.
    
- **Run the configuration server**
    
    We created the systemd service for the configuration server, but we never activated it. We’ll do that now using the following commands as root.
    
    ```bash
    systemctl daemon-reload
    systemctl enable --now backup-conf-httpd.service
    ```
    
    This will *enable* and *start* the service, meaning it’ll tell systemd to start the service automatically on boot and start it manually now.
    

### Nodes

The following section will go over the process to manually set up a node as part of the backup system. Skip to **********************************************Automatic provisioning********************************************** for a single-command method to set up nodes.

### Setup

#### Setup

The setup for each node is in some ways more complex and in some ways simpler than the setup for the backup server. The node must be configured to perform the following process at given times:

1. Pull configuration data from backup server
2. Parse configuration data and update files when needed
3. Create a backup archive

We’ll create a Python script to do this, which we’ll call the *************client script*************. Being Raspberry Pi’s, all of the nodes should already have Python ≥3.7 installed. Python has the ability to fetch data over HTTP⁵ and parse JSON, so we don’t need any additional software for that.

The following steps must be taken to set up the node:

- **Install packages**
    
    We need to install Borg and the OpenSSH client on the node:
    
    ```bash
    apt install borgbackup openssh-client
    ```
    
- **Create the systemd units**
    
    We need to create two systemd units on the node: a service and a timer. The service is what performs the backups, and the timer is responsible for running the service at the times specified in the system’s configuration file.
    
    The backup service consists of the file `/usr/local/lib/systemd/system/backup.service` with the following contents. Creating this file (and possibly the parent directory) will require root access.
    
    ```ini
    [Unit]
    Description=Back up user files
    Requires=network-online.target network.target
    After=network-online.target network.target
    Before=shutdown.target
    
    [Service]
    StateDirectory=backup_client
    Type=oneshot
    ExecStart=/usr/local/lib/backup_client.py
    ```
    
    Notice that unlike the last systemd service we created, this one does not have an `[Install]` section. We want to place this in a separate file so that the client script can update it if the configuration changes. Run the following commands as root on the node to create this new file:
    
    ```bash
    mkdir -vp /etc/systemd/system/backup.service.d
    cat << 'EOF' > /etc/systemd/system/backup.service.d/00-triggers.conf
    [Install]
    WantedBy=shutdown.target
    EOF
    ```
    
    This will trigger the backup service before the node shuts down. In practice, this file’s contents won’t matter because we’ll run the backup service once manually, which will update the trigger file.
    
    After creating the systemd unit files, run the following command as root to reload systemd:
    
    ```bash
    systemctl daemon-reload
    ```
    
    The second unit we need to create is the timer. While the trigger above can run the backup service when the node shuts down, it cannot run it at specific times. To do that we need a systemd timer. Create the file `/usr/local/lib/systemd/system/backup.timer` with the following contents:
    
    ```ini
    [Unit]
    Description=Timer for backup service
    
    [Timer]
    Unit=backup.service
    WakeSystem=on
    
    [Install]
    WantedBy=timers.target
    ```
    
    Like with the backup service unit, we want to create a separate file which will contain the list of times at which the timer will fire. To do so, run the following commands as root.
    
    ```bash
    mkdir -vp /etc/systemd/system/backup.timer.d
    echo '[Timer]' > /etc/systemd/system/backup.timer.d/00-times.conf
    ```
    
    We don’t actually specify any times yet. The client script will generate those from the configuration it fetches.
    
    Once both the service and timer units are created, we need to enable them. Note that ********enabling******** the units is different from ********starting******** them. Enabled units will be started automatically by systemd when the target listed in the `WantedBy=` directive is started. On the other hand, ********starting******** a unit means manually triggering it. Starting the backup service will be the last step of the node’s setup process.
    
    To enable the units, run the following two commands as root.
    
    ```bash
    systemctl daemon-reload
    systemctl enable backup.service backup.timer
    ```
    
- **Create the client script**
    
    The client script is a large, complex script, so I won’t go over how it works here. To install the client script, download `client.py` and save it as `/usr/local/lib/backup_client.py` on the node. If the `/usr/local/lib` folder doesn’t exist, you can create it:
    
    ```bash
    mkdir -vp /usr/local/lib
    ```
    
    Once the script file is installed, we need to make it executable by running the following command as root.
    
    ```bash
    chmod 0754 /usr/local/lib/backup_client.py
    ```
    
    The client script is a larger file and performs many functions, so I won’t explain it in depth here. The script file is `client.py` and should be saved as `/usr/local/lib/backup_client.py`. The parent directories may need to be created manually.
    
    Once the script is installed, make it executable by running the following command as root.
    
    ```bash
    chmod 0700 /usr/local/lib/backup_client.py
    ```
    
- ************************************************Set the node’s hostname************************************************
    
    We need each node to have its own hostname so we can differentiate the backups on the backup server. You can choose any hostname for each node as long as no two nodes have the same hostname.
    
    To set the hostname, run the following command as root, replacing the placeholder with your desired hostname. Avoid having whitespace in the hostname, as this could cause problems if the hostname is used in file paths.
    
    ```bash
    hostnamectl hostname $YOUR_HOSTNAME
    ```
    
- **Install the SSH key**
    
    To allow the node to log in to the backup server and create a backup, we need to give it the SSH key we generated. Copy the `node_key` file from the backup server and save it as `/usr/local/share/backup_client/ssh_key`. You may need to create the parent directory first. Make sure that the file is only readable by root, not normal users:
    
    ```bash
    chmod 0600 /usr/local/share/backup_client/ssh_key
    ```
    
    The client script will automatically make a copy of the key that is accessible by the user whose files are being backed up.
    
- ******************************************Run the client script******************************************
    
    We want to run the client script manually after installing all the parts so it can pull the latest configuration from the backup server and update the necessary files.
    
    On the node, run the following command as root to run the client script.
    
    ```bash
    systemctl start backup.service
    ```
    
    If the client script runs successfully, this will not print any output. To see the log messages from the client script, use the following command.
    
    ```bash
    journalctl -xe -u backup.service
    ```
    
    To see the log update in real time as the service is running, replace `-xe` with `-f`.
    

⁵ The `requests` package for Python is installed by default on Raspberry Pi OS.

#### Automatic provisioning

**********Setup**********

In order to achieve the goal of being easily scalable, we need to make it easier to provision (i.e. set up) a node. To do this, we’ll create a shell script, which is a file containing a collection of shell commands to be run in series.

We also want to serve the script from the backup server so that copying it to a new node is easy. Once we do this, provisioning a node will only require running a single command on it.

- **Create the provisioning script**
    
    The provisioning script is a large file, since it has to include all of the systemd units we’ve created as well as the client script. Therefore I won’t include or explain the contents here. Just download `provision.sh` and save it as `~/provision.sh` as the backup custodian on the backup server.
    
    The provisioning script must know the IP address of the backup server, as it downloads the client script and SSH key from the server. The IP address is configured in the first few lines of the script. Edit the provisioning script and ensure the settings are correct before attempting to provision a node. The same goes for the client script. It needs to contain the correct IP address the first time it is run so that it can pull the configuration. After that, the IP address can be updated in the configuration file and it’ll be pulled by all the nodes.
    
- **Serve the script from the configuration server**
    
    This step is simple. All we need to do is create another symbolic link from the configuration data directory to the script we just created. We’ll put it in a subdirectory for organization purposes.
    
    ```bash
    mkdir -vp ~/.conf_server_data/setup
    ln -s ~/provision.sh ~/.conf_server_data/setup/provision.sh
    ```
    
- **Serve auxiliary files from the configuration server**
    
    The provisioning script needs to install the client script and SSH key on the node. This means it either needs to include those files inside the script, or it needs to be able to download them. The former option would make it difficult to update either the client script or the SSH key, so we’ll choose the latter.
    
    This means we need to create a symbolic link to those two files in the configuration server’s data directory. Run the following two commands as the backup custodian.
    
    ```bash
    ln -vs ~/client.py ~/.conf_server_data/setup/client.py
    ln -vs ~/node_key ~/.conf_server_data/setup/node_key
    ```
    
    The `node_key` file already exists on the server. The client script doesn’t, so download the [file from above](https://www.notion.so/Raspberry-Pi-Backup-System-599ef1eacbc44781ae3d198d03363775) and save it as `~/client.py` as the backup custodian.
    

**********Usage**********

After the above setup has been completed for the backup server, we will be able to fully provision a new node by running the following command on the node. Obviously, replace the `${SERVER_IP}` placeholder with the IP address of the backup server.

```bash
curl http://${SERVER_IP}:36888/setup/provision.sh | sudo sh
```

If already running as root, omit `sudo` from the command.

The provisioning script requires the user to do only one thing, which is entering a new hostname if the default one has not already been changed. If the default hostname of `raspberrypi` has been changed, no user interaction is required.

### Network

The nodes need to communicate with the backup server, which is done over a network. The structure of the network does not matter, as long as the nodes can reach the backup server. In order to do that, the backup server needs either a fixed IP address or a resolvable domain name. Based on these criteria, we have two viable options:

1. Use the LAN with a fixed IP address for the backup server.
2. Use a service such as [Cloudflare Tunnels](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps) to expose the backup server.

Both options have benefits and downsides. Option 1 requires less initial setup and prevents us from relying on external services. However, if the LAN infrastructure changes, the nodes may no longer be able to reach the backup server. Also, the backup server and the nodes must all be on the same LAN.

Option 2 requires more setup, but it prevents us from running into any issues with the LAN structure because we only require outgoing connections to the Internet. However, it exposes the backup server to the open Internet, meaning it must be more heavily secured. Also, it requires the use of an external service.

Option 1 aligns more closely with our goals, so that’s the route we’ll take.

#### Required setup

There is relatively little network setup required. The only criterion is that the node can reach the backup server over the network at a static address. We’ll achieve this by configuring `dhcpcd(8)` on the backup server to use a static IP address.

`dhcpcd` is a Dynamic Host Configuration Protocol (DHCP) client, which is responsible for getting the network configuration (e.g. IP address, router address, DNS servers) when connecting to the network. We want it to use a static IP address rather than one provided by the DHCP server.

Follow the two steps below to do so.

- ****************************************************************************Identify desired network configuration****************************************************************************
    
    First, identify the network interface that is connected to the same network as the nodes. Run the following command on the backup server.
    
    ```bash
    ip addr
    ```
    
    This will produce output like the following:
    
    ```
    1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
        link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
        inet 127.0.0.1/8 scope host lo
           valid_lft forever preferred_lft forever
    81: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default 
        link/ether 02:42:ac:18:00:02 brd ff:ff:ff:ff:ff:ff link-netnsid 0
        inet 172.24.0.2/16 brd 172.24.255.255 scope global eth0
           valid_lft forever preferred_lft forever
    ```
    
    The green text is the interface name, and the orange text is its IP address (plus a subnet mask). It won’t be colored in the command’s output. You’ll just have to identify the right parts.
    
    Take note of the network interface name and the IP address. We’ll use these in the next step. If you have another IP address you want to assign instead, use that.
    
- ******************************************Configure `dhcpcd(8)`**
    
    On the backup server, edit the file `/etc/dhcpcd.conf`. This will require root permissions. Insert the following lines at the bottom of the file. Replace the placeholders with the values from the last step.
    
    ```html
    interface <INTERFACE>
    inform ip_address=<IP_ADDRESS>
    ```
    
    This will make `dhcpcd` tell the DHCP server that we want the given IP address, rather than using a random one given by the DHCP server.
    
    After making the change, either disconnect and reconnect the backup server from the network or run the following command as root to restart `dhcpcd`:
    
    ```bash
    systemctl restart dhcpcd.service
    ```
    

## Classroom setup instructions

<aside>
⚠️ This section is specific to the classroom that the system was designed for. It may need to be adapted for use in other classrooms.
</aside>

To set up the Raspberry Pi backup system for the classroom, [follow the steps above](https://www.notion.so/Raspberry-Pi-Backup-System-599ef1eacbc44781ae3d198d03363775) to set up a backup server and ensure the network settings are [configured properly](https://www.notion.so/Raspberry-Pi-Backup-System-599ef1eacbc44781ae3d198d03363775). Then edit the configuration file as required. Once that is done, have each student follow the instructions on the following page:

[Node setup instructions](https://www.notion.so/Node-setup-instructions-367beefc48794fc5a2a9df8e03b53a93)
