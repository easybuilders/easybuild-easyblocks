##
# Copyright 2009-2020 Ghent University
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
EasyBuild support for building and installing RELION, implemented as an easyblock

@author: Alex Domingo (Vrije Universiteit Brussel)
"""

import os
import stat

from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import adjust_permissions, mkdir, write_file
from easybuild.tools.modules import get_software_root

from easybuild.easyblocks.generic.cmakemake import CMakeMake


class EB_RELION(CMakeMake):
    """Support for building/installing RELION"""

    def __init__(self, *args, **kwargs):
        """Constructor of RELION easyblock."""
        super(EB_RELION, self).__init__(*args, **kwargs)

        # check requested job scheduler
        known_queque_cmds = ['qsub', 'sbatch']

        if self.cfg['queue_cmd'] not in known_queque_cmds:
            raise EasyBuildError(
                "Unknown 'queue_cmd': %s. Please use %s", self.cfg['queue_cmd'], " or ".join(known_queque_cmds)
            )

        # job template filenames
        self.job_filename = {
            'qsub': 'qsub_torque.bash',
            'sbatch': 'sbatch_slurm.bash',
        }

        # static options in the job template header
        self.job_header_opts = {
            'qsub': {
                'prefix': "#PBS",
                'name': "-N %s",
                'queue': "-q %s",
                'errfile': "-e %s",
                'outfile': "-o %s",
                'mpinodes': "-l nodes=%s",
                'threads': ":ppn=%s",  # appended to mpinodes with rsrc_sep
                'rsrc_sep': '',
            },
            'sbatch': {
                'prefix': "#SBATCH",
                'name': "-J %s",
                'queue': "%s",
                'errfile': "-e %s",
                'outfile': "-o %s",
                'mpinodes': "-n %s",
                'threads': "-c %s",  # appended to mpinodes with rsrc_sep
                'rsrc_sep': ' ',
            },
        }

        # extra options in the job template header
        self.job_header_extras = {
            'qsub': {
                "Hours of walltime": "-l walltime=%s:00:00",
                "Number of GPUs": ":gpus=%s",  # appended to mpinodes with rsrc_sep
                "Account": "-A %s",
            },
            'sbatch': {
                "Hours of walltime": "-t %s:00:00",
                "Number of GPUs": "--gres=gpu:%s",  # appended to mpinodes with rsrc_sep
                "Account": "-A %s",
            },
        }

        # body of job template
        self.job_body = {
            'qsub': [
                "cd $PBS_O_WORKDIR",
                "mpirun -n XXXmpinodesXXX XXXcommandXXX",
            ],
            'sbatch': [
                "srun XXXcommandXXX",
            ],
        }

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for RELION"""
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            # RELION provides a default template to submit jobs in a generic batch scheduler with qsub
            'queue_cmd': [None, "Command to submit jobs to the scheduler", MANDATORY],
            'queue_name': [None, "Name of the default submission queue for RELION", MANDATORY],
            'qsub_mpi': [4, "Default number of MPI procs showed in RELION's GUI", CUSTOM],
            'qsub_mpi_max': [20, "Maximum number of MPI procs allowed in RELION's GUI", CUSTOM],
            'qsub_mpi_interact': [20, "Maximum number of MPI procs allowed in RELION's interactive session", CUSTOM],
            'qsub_threads': [4, "Default number of threads showed in RELION's GUI", CUSTOM],
            'qsub_threads_max': [20, "Maximum number of threads allowed in RELION's GUI", CUSTOM],
            'qsub_ppn': [1, "Default number of cores per node", CUSTOM],
            'qsub_ppn_edit': [False, "Allow user to change the minimum dedicated cores per node", CUSTOM],
            'qsub_extra_params': [[], ("List of extra parameters for the submission command (RELION_QSUB_EXTRA)"
                                       "Each element is a name/value pair (tuple)"), CUSTOM],
            'tmp': ['/tmp', "Default scratch directory in RELION's GUI", CUSTOM],
            'cuda_compute_capabilities': [[], "List of CUDA compute capabilities to build with", CUSTOM],
        })
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def prepare_step(self, *args, **kwargs):
        """Prepare build environment and construct list of extra job parameters (RELION_QSUB_EXTRA)"""
        super(EB_RELION, self).prepare_step(*args, **kwargs)

        # extra job parameters: added in the job template and to RELION's GUI through environment variables
        self.qsub_extra_params = list()
        # first extra qsub parameter is always hours of walltime
        qsub_extra_hours = ("Hours of walltime", '24')
        self.qsub_extra_params.append(qsub_extra_hours)
        # add number of GPUs with CUDA
        if get_software_root('CUDA'):
            qsub_extra_gpus = ("Number of GPUs", '1')
            self.qsub_extra_params.append(qsub_extra_gpus)
        # append user's qsub extra parameters
        self.qsub_extra_params.extend(self.cfg['qsub_extra_params'])
        self.log.debug("RELION extra job parameters: %s" % self.qsub_extra_params)

    def configure_step(self):
        """Configuration with CMake including additional settings"""

        # generic configopts
        self.cfg.update('configopts', '-DCMAKE_SHARED_LINKER_FLAGS="-lpthread"')

        if get_software_root('CUDA'):
            # list of CUDA compute capabilities to use can be specifed in two ways (where (2) overrules (1)):
            # (1) in the easyconfig file, via the custom cuda_compute_capabilities;
            # (2) in the EasyBuild configuration, via --cuda-compute-capabilities configuration option;
            ec_cuda_cc = self.cfg['cuda_compute_capabilities']
            cfg_cuda_cc = build_option('cuda_compute_capabilities')
            cuda_cc = cfg_cuda_cc or ec_cuda_cc or []
            if not cuda_cc:
                raise EasyBuildError("Can't build RELION with CUDA support "
                                     "without specifying 'cuda-compute-capabilities'")
            cuda_cc = [cc.replace('.', '') for cc in cuda_cc]
            # lowest supported CUDA capability in RELION v3 is 3.5
            if min(cuda_cc) < 3.5:
                raise EasyBuildError("Can't build RELION with CUDA support, minimum CUDA capability supported is 3.5")
            # generate CUDA gencodes
            cuda_gencodes = ';'.join(['-gencode arch=compute_%s,code=sm_%s' % (cc, cc) for cc in cuda_cc])
            cuda_arch = "%s %s" % (min(cuda_cc), cuda_gencodes)
            # enable CUDA
            cuda_configopts = {
                'CUDA': 'ON',
                'CudaTexture': 'ON',
                'CUDA_ARCH': cuda_arch,
            }
        else:
            # disable CUDA and enable CPU optimizations
            cuda_configopts = {
                'CUDA': 'OFF',
                'CudaTexture': 'OFF',
                'ALTCPU': 'ON',
            }

        for cfg, opt in cuda_configopts.items():
            self.cfg.update('configopts', '-D%s="%s"' % (cfg, opt))

        return super(EB_RELION, self).configure_step()

    def post_install_step(self):
        """Install job script template for the selected scheduler"""
        super(EB_RELION, self).post_install_step()

        # pick job options and commands for current job scheduler
        job_header = self.job_header_opts[self.cfg['queue_cmd']]
        job_header.update(self.job_header_extras[self.cfg['queue_cmd']])
        job_body = self.job_body[self.cfg['queue_cmd']]

        # placeholder of template options  used by RELION
        placeholder = "XXX%sXXX"

        # preface: name, output/error, walltime (extra1)
        job_template = ["#!/bin/bash"]

        if self.cfg['queue_cmd'] == 'qsub':
            # load user's environment in the job session
            directive = ' '.join([job_header['prefix'], '-V'])
            job_template.append(directive)

        for opt in ['name', 'outfile', 'errfile']:
            directive = ' '.join([job_header['prefix'], job_header[opt]])
            directive = directive % placeholder % opt
            job_template.append(directive)

        # resources: nodes, threads
        resources = [job_header[rsrc] % placeholder % rsrc for rsrc in ['mpinodes', 'threads']]

        # extra job parameters: parse into their own list
        extra_directives = []
        for n, (extra_param, _) in enumerate(self.qsub_extra_params):
            extra_num = 'extra%s' % (n + 1)
            if extra_param == "Number of GPUs":
                # special case: add GPUs to resources
                resources.append(job_header[extra_param] % placeholder % extra_num)
            elif extra_param in job_header:
                # add corresponding option for known extra parameters
                directive = ' '.join([job_header['prefix'], job_header[extra_param]])
                directive = directive % placeholder % extra_num
                extra_directives.append(directive)
            else:
                # by default add the plain extra parameter to the template
                directive = ' '.join([job_header['prefix'],  placeholder % extra_num])
                extra_directives.append(directive)

        # resources: add nodes, threads and GPUs to template
        resources = job_header['rsrc_sep'].join(resources)
        resources = ' '.join([job_header['prefix'], resources])
        job_template.append(resources)

        # extra job parameters: add to template
        job_template.extend(extra_directives)

        # epilog: queue
        for opt in ['queue']:
            queue_opt = ' '.join([job_header['prefix'], job_header[opt]])
            queue_opt = queue_opt % placeholder % opt
            job_template.append(queue_opt)

        # job body
        job_body.append('')  # ensure new line character at end of file
        job_template.extend(job_body)

        # install job template
        bindir = os.path.join(self.installdir, 'bin')
        mkdir(bindir)

        job_template_file = os.path.join(bindir, self.job_filename[self.cfg['queue_cmd']])
        job_template_txt = '\n'.join(job_template)
        write_file(job_template_file, job_template_txt)

        # add full r-x permissions to job template
        rx_perms = stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
        adjust_permissions(job_template_file, rx_perms, add=True)

        self.log.info("Job script template for RELION created and installed succesfully: %s", job_template_file)

    def sanity_check_step(self):
        """Custom sanity check for RELION"""

        # check files and directories
        binaries = ['relion', self.job_filename[self.cfg['queue_cmd']]]

        custom_paths = {
            'files': [os.path.join("bin", x) for x in binaries],
            'dirs': [],
        }

        # check commands
        custom_commands = ["relion --version"]

        return super(EB_RELION, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """Configure RELION runtime environment"""

        relion_envars = {
            'RELION_QSUB_COMMAND': self.cfg['queue_cmd'],  # Default for 'Queue submit command'
            'RELION_QUEUE_NAME': self.cfg['queue_name'],  # Default for 'Queue Name"
            'RELION_QSUB_NRMPI': self.cfg['qsub_mpi'],  # Default for 'Number of MPI procs'
            'RELION_MPI_MAX': self.cfg['qsub_mpi_max'],  # Maximum number of MPI processes available from the GUI
            'RELION_ERROR_LOCAL_MPI': self.cfg['qsub_mpi_interact'],  # Maximum MPI tasks in interactive sessions
            'RELION_QSUB_NRTHREADS': self.cfg['qsub_threads'],  # Default for 'Number of threads'
            'RELION_THREAD_MAX': self.cfg['qsub_threads_max'],  # Maximum number of threads available from the GUI
            'RELION_MINIMUM_DEDICATED': self.cfg['qsub_ppn'],  # Default for 'Minimum dedicated cores per node'
            # Allow user to change the 'Minimum dedicated cores per node'
            'RELION_ALLOW_CHANGE_MINIMUM_DEDICATED': '1' if self.cfg['qsub_ppn_edit'] else '0',
            'RELION_SCRATCH_DIR': self.cfg['tmp'],  # Default scratch directory in the GUI
        }

        # add extra qsub parameters
        envar_basename = 'RELION_QSUB_EXTRA'
        envar_default_suffix = 'DEFAULT'
        for n, (param_desc, param_default) in enumerate(self.qsub_extra_params):
            envar_desc = "%s%s" % (envar_basename, n + 1)
            envar_default = "%s_%s" % (envar_desc, envar_default_suffix)
            extra_envars = {envar_desc: param_desc, envar_default: param_default}
            relion_envars.update(extra_envars)

        # add count of qsub extra parameters
        relion_envars.update({'RELION_QSUB_EXTRA_COUNT': len(self.qsub_extra_params)})

        # external CTFFIND
        if get_software_root('ctffind'):
            relion_envars.update({'RELION_CTFFIND_EXECUTABLE': 'ctffind'})
            # shell used to launch CTFFIND/GCTF in CtfFind jobs
            if get_software_root('tcsh'):
                relion_envars.update({'RELION_SHELL': 'csh'})

        # external Gctf
        if get_software_root('Gctf'):
            relion_envars.update({'RELION_GCTF_EXECUTABLE': 'Gctf'})

        # external MotionCor2
        if get_software_root('MotionCor2'):
            relion_envars.update({'RELION_MOTIONCOR2_EXECUTABLE': 'motioncor2'})

        # add environment variables to module file
        txt = super(EB_RELION, self).make_module_extra()

        for envar_name, envar_val in relion_envars.items():
            txt += self.module_generator.set_environment(envar_name, envar_val)

        return txt
