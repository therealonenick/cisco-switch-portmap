# cisco-switch-portmap
Dirty tool to discover and migrate large sets of switches and switch-stacks

## Overview

This tool came out of a need to migrate large switch stacks while also re-wiring a closet while retaining configured VLAN Mappings.

## Usage

1. Specifically formatted CSV (discoverSwitches.csv) of switches and their positions, logins..etc to be used to scan the systems.
2. A Second specifically formatted CSV (switchMapData.csv) that identifies the patching information for the Patch Panel -> Switch Ports.

Utilizing both, the tool with re-map all appropriate ports to their new configurations, and prodide a standardized switch configuration.


## Notes

Some attempt was made to use a serial connection to auto provision however some hiccups were faced.  Instead we opted to just output the CFG and then paste it into the console in chunks. Very much not ideal, but that was the time-crunch we were in.

Many optimizations to be had and not the cleanest code but it got the job done.  This was used quite a bit ago but was asked by a colleauge to post it so they could reuse it.  So here it is!


## To Do:

Update the Readme with appropriate information and instructions.

### Usage provided without warrenty.

