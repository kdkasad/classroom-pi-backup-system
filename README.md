# Raspberry Pi Backup System for Classrooms

A system designed to make it easy to create backups for a whole classroom of
Raspberry Pi computers.

For documentation of the system, e.g. what it does and how it works, see the
article linked below:
<https://kasad.notion.site/Raspberry-Pi-Backup-System-for-Classrooms-599ef1eacbc44781ae3d198d03363775>

The rest of the README file documents only the files in this repository.

## Building

The provisioning script (`provision.sh`) and the client script (`client.py`)
both contain the initial server IP address and HTTPd port. To make this easier
to configure, we generate these files using [GNU
M4](https://www.gnu.org/software/m4/) to expand macros in source files. The macros' values are derived from `config.mk`.

To build the scripts,
1. Change the settings in `config.mk` as necessary.
2. Then run the command `make` to generate `provision.sh` and `client.py`.

The provisioning script must also contain the contents of some of the
files in the `node` directory. This is also handled by M4 and the `Makefile`.

## Repository structure

The repository is sectioned into three main segments:
    1. Loose files
    2. The `node` directory
    3. The `server` directory

### Loose files

Several files exist in the repository root, chiefly `provision.sh.in` and
`client.py`. These files are used in both the server and the node and are the
main files that will be edited, so they live in the repository root. They are
symbolically linked to from within the `node` and `server` directory trees.

The `Makefile` is a script-like file that will perform any
processing/compilation necessary to build the files in the repository.

### The `node` directory

The `node` directory mimics the filesystem structure of a node and contains the
node-specific files. Running `cp -aLT ./node /` as root from this repository
will copy all necessary files into the correct locations on a node.

### The `server` directory

The `server` directory mimics the filesystem structure of a node and contains
the node-specific files. Unlike with nodes, copying these files is not enough to
create a functioning server because some additional configuration needs to
happen, e.g. creating the `backup` user.

