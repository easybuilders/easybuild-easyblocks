##
# Copyright 2020-2024 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
EasyBuild support for building and installing Metagenome-Atlas, implemented as an easyblock.

@author: Pavel Grochal (INUITS)
"""
import os
import stat

from easybuild.tools.filetools import adjust_permissions, write_file
from easybuild.easyblocks.generic.pythonpackage import PythonPackage


class EB_Metagenome_Atlas(PythonPackage):
    """
    Support for building/installing Metagenome-Atlas.
    """

    def post_install_step(self):
        """Create snakemake config files"""

        # https://metagenome-atlas.readthedocs.io/en/latest/usage/getting_started.html#set-up-of-cluster-execution
        # Files were obtained by:
        # cookiecutter https://github.com/metagenome-atlas/clusterprofile.git -o ~/.config/snakemake

        snakemake_conf_dir = os.path.join(self.installdir, 'snakemake-config')

        cluster_config_file = os.path.join(snakemake_conf_dir, 'cluster_config.yaml')
        config_file = os.path.join(snakemake_conf_dir, 'config.yaml')
        key_mapping = os.path.join(snakemake_conf_dir, 'key_mapping.yaml')
        lsf_status = os.path.join(snakemake_conf_dir, 'lsf_status.py')
        pbs_status = os.path.join(snakemake_conf_dir, 'pbs_status.py')
        scheduler = os.path.join(snakemake_conf_dir, 'scheduler.py')
        slurm_status = os.path.join(snakemake_conf_dir, 'slurm_status.py')

        write_file(cluster_config_file, CLUSTER_CONFIG_FILE_TEXT)
        write_file(config_file, CONFIG_FILE_TEXT % cluster_config_file)
        write_file(key_mapping, KEY_MAPPING_TEXT)
        write_file(lsf_status, LSF_STATUS_TEXT)
        write_file(pbs_status, PBS_STATUS_TEXT)
        # scheduler file includes small tweak from original file in git
        write_file(scheduler, SCHEDULER_TEXT)
        write_file(slurm_status, SLURM_STATUS_TEXT)

        # make sure .py scripts are executable
        adjust_permissions(lsf_status, stat.S_IXUSR)
        adjust_permissions(pbs_status, stat.S_IXUSR)
        adjust_permissions(scheduler, stat.S_IXUSR)
        adjust_permissions(slurm_status, stat.S_IXUSR)

    def sanity_check_step(self):
        """
        Custom sanity check for Metagenome-Atlas.
        """
        custom_paths = {
            'files': ['bin/atlas'],
            'dirs': [os.path.join('lib', 'python%(pyshortver)s', 'site-packages')],
        }
        custom_commands = [
            'atlas --version',
            'atlas init --help',
            'atlas run --help',
        ]
        super(PythonPackage, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)


# obtained from
# https://github.com/metagenome-atlas/clusterprofile/blob/master/{{cookiecutter.profile_name}}/cluster_config.yaml
CLUSTER_CONFIG_FILE_TEXT = r"""
__default__:
  nodes: 1
"""

# obtained from
# https://github.com/metagenome-atlas/clusterprofile/blob/master/{{cookiecutter.profile_name}}/config.yaml
# modified cores to 1
CONFIG_FILE_TEXT = r"""
restart-times: 0
cluster-config: "%s" #abs path
cluster: "scheduler.py" #
cluster-status: "slurm_status.py" #
max-jobs-per-second: 10
max-status-checks-per-second: 10
cores: 1 # how many jobs you want to submit to your cluster queue
local-cores: 1
rerun-incomplete: true  # recomended for cluster submissions
keep-going: false
"""

# obtained from
# https://github.com/metagenome-atlas/clusterprofile/blob/master/{{cookiecutter.profile_name}}/key_mapping.yaml
KEY_MAPPING_TEXT = r"""
# only parameters defined in key_mapping (see below) are passed to the command in the order specified.
system: "slurm" #check if system is defined below

slurm:
  command: "sbatch --parsable"
  key_mapping:
    name: "--job-name={}"
    threads: "-n {}"
    mem: "--mem={}g"
    account: "--account={}"
    queue: "--partition={}"
    time: "--time={}"
    nodes: "-N {}"
pbs:
  command: "qsub"
  key_mapping:
    name: "-N {}"
    account: "-A {}"
    queue: "-q {}"
    threads: "-l nodes=1:ppn={}" # always use 1 node
    mem: "-l mem={}gb"
    time: "-l walltime={}00" #min= seconds x 100
lsf:
  command: "bsub -e lsf_%J.log -o lsf_%J.log"
  key_mapping:
    queue: "-q {}"
    name: "-J {}"
    threads: "-n {}"
    mem: '-R "rusage[mem={}000]"'
    account: "-P {}"
    nodes: "-C {}"

# for other cluster systems see: https://slurm.schedmd.com/rosetta.pdf
"""

# obtained from
# https://github.com/metagenome-atlas/clusterprofile/blob/master/{{cookiecutter.profile_name}}/lsf_status.py
LSF_STATUS_TEXT = r"""
#!/usr/bin/env python3

import os
import sys
import warnings
import subprocess

jobid = sys.argv[1]

out= subprocess.run(['bjobs','-noheader',jobid],stdout=subprocess.PIPE).stdout.decode('utf-8')

state = out.strip().split()[2]

map_state={"PEND":'running',
           "RUN":'running',
           "PROV":"running",
           "WAIT":'running',
           "DONE":'success',
           "":'success'}

print(map_state.get(state,'failed'))
"""

# obtained from
# https://github.com/metagenome-atlas/clusterprofile/blob/master/{{cookiecutter.profile_name}}/pbs_status.py
PBS_STATUS_TEXT = r"""
#!/usr/bin/env python3

import sys
import subprocess
import xml.etree.cElementTree as ET

jobid = sys.argv[1]

try:
    res = subprocess.run("qstat -f -x {}".format(jobid), check=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)

    xmldoc = ET.ElementTree(ET.fromstring(res.stdout.decode())).getroot()
    job_state = xmldoc.findall('.//job_state')[0].text

    if job_state == "C":
        exit_status = xmldoc.findall('.//exit_status')[0].text
        if exit_status == '0':
            print("success")
        else:
            print("failed")
    else:
        print("running")

except (subprocess.CalledProcessError, IndexError, KeyboardInterrupt) as e:
    print("failed")
"""

# obtained from
# https://github.com/metagenome-atlas/clusterprofile/blob/master/{{cookiecutter.profile_name}}/scheduler.py
# enhanced with parsing below comment '# get jobid if the string contains cluster name as well separated by ;'
SCHEDULER_TEXT = r"""
#!/usr/bin/env python3

import sys, os
from subprocess import Popen, PIPE
import yaml

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

# let snakemake read job_properties
from snakemake.utils import read_job_properties

jobscript = sys.argv[1]
job_properties = read_job_properties(jobscript)

#default paramters defined in cluster_spec (accessed via snakemake read_job_properties)
cluster_param= job_properties["cluster"]

if job_properties["type"]=='single':
    cluster_param['name'] = job_properties['rule']
elif job_properties["type"]=='group':
    cluster_param['name'] = job_properties['groupid']
else:
    raise NotImplementedError(f"Don't know what to do with job_properties['type']=={job_properties['type']}")

# don't overwrite default parameters if defined in rule (or config file)
if ('threads' in job_properties) and ('threads' not in cluster_param):
    cluster_param["threads"] = job_properties["threads"]
for res in ['time','mem']:
    if (res in job_properties["resources"]) and (res not in cluster_param):
        cluster_param[res] = job_properties["resources"][res]

# time in hours
if "time" in cluster_param:
    cluster_param["time"]=int(cluster_param["time"]*60)

# check which system you are on and load command command_options
key_mapping_file=os.path.join(os.path.dirname(__file__),"key_mapping.yaml")
command_options=yaml.load(open(key_mapping_file),
                          Loader=yaml.BaseLoader)
system= command_options['system']
command= command_options[system]['command']

key_mapping= command_options[system]['key_mapping']

# construct command:
for  key in key_mapping:
    if key in cluster_param:
        command+=" "
        command+=key_mapping[key].format(cluster_param[key])

command+=' {}'.format(jobscript)

eprint("submit command: "+command)

p = Popen(command.split(' '), stdout=PIPE, stderr=PIPE)
output, error = p.communicate()
if p.returncode != 0:
    raise Exception("Job can't be submitted\n"+output.decode("utf-8")+error.decode("utf-8"))
else:
    res= output.decode("utf-8")

    if system=='lsf':
        import re
        match = re.search(r"Job <(\d+)> is submitted", res)
        jobid = match.group(1)

    elif system=='pbs':
        jobid= res.strip().split('.')[0]

    else:
        try:
            jobid= int(res.strip().split()[-1])
        except ValueError as e:
            # get jobid if the string contains cluster name as well separated by ;
            jobid = int(res.strip().split()[-1].split(';')[0])

    print(jobid)
"""

# obtained from
# https://github.com/metagenome-atlas/clusterprofile/blob/master/{{cookiecutter.profile_name}}/slurm_status.py
SLURM_STATUS_TEXT = r"""
#!/usr/bin/env python3

import re
import subprocess as sp
import shlex
import sys
import time
import logging
logger = logging.getLogger("__name__")

STATUS_ATTEMPTS = 20

jobid = sys.argv[1]

for i in range(STATUS_ATTEMPTS):
    try:
        sacct_res = sp.check_output(shlex.split("sacct -P -b -j {} -n".format(jobid)))
        res = {x.split("|")[0]: x.split("|")[1] for x in sacct_res.decode().strip().split("\n")}
        break
    except sp.CalledProcessError as e:
        logger.error("sacct process error")
        logger.error(e)
    except IndexError as e:
        pass
    # Try getting job with scontrol instead in case sacct is misconfigured
    try:
        sctrl_res = sp.check_output(shlex.split("scontrol -o show job {}".format(jobid)))
        m = re.search("JobState=(\w+)", sctrl_res.decode())
        res = {jobid: m.group(1)}
        break
    except sp.CalledProcessError as e:
        logger.error("scontrol process error")
        logger.error(e)
        if i >= STATUS_ATTEMPTS - 1:
            print("failed")
            exit(0)
        else:
            time.sleep(1)

status = res[jobid]

if (status == "BOOT_FAIL"):
    print("failed")
elif (status == "OUT_OF_MEMORY"):
    print("failed")
elif (status.startswith("CANCELLED")):
    print("failed")
elif (status == "COMPLETED"):
    print("success")
elif (status == "DEADLINE"):
    print("failed")
elif (status == "FAILED"):
    print("failed")
elif (status == "NODE_FAIL"):
    print("failed")
elif (status == "PREEMPTED"):
    print("failed")
elif (status == "TIMEOUT"):
    print("failed")
# Unclear whether SUSPENDED should be treated as running or failed
elif (status == "SUSPENDED"):
    print("failed")
else:
    print("running")
"""
