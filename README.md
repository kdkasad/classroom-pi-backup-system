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
files in the `node` directory. This too is handled by M4 and the `Makefile`.

## Repository structure

The repository is sectioned into three parts:
    1. Loose files - Consists of build system files and files shared between
       nodes and the server
    2. The `node` directory - Contains node-specific files and mimics the
       directory structure of a node.
    3. The `server` directory - Contains server-specific files and mimics the
       directory structure of a server.

## To-do list

- [ ] Add automated testing capability
