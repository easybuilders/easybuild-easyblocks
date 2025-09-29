##
# Copyright 2009-2019 Ghent University
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
EasyBuild support for building and installing HPL, implemented as an easyblock

@author: Victor Holanda (CSCS)
"""

import os
import shutil

import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import get_module_syntax


class EB_Darshan(ConfigureMake):
    """
    Darshan runtime and util packages
    """

    @staticmethod
    def extra_options():
        extra_vars = {
            'mem_align': ["8", "determines if the buffer for a read or write operation is aligned in memory.", CUSTOM],
            'logpath_env': ["DARSHAN_LOG_DIR_PATH", "specifies an environment variable to use to determine the log path at run time", CUSTOM],
            'jobid_env':   ['SLURM_JOB_ID', "specifies the environment variable that Darshan should check to determine the jobid of a job", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars)

    def configure_step(self, util=False):
        """
        Create Make.UNKNOWN file to build from
        - provide subdir argument so this can be reused in HPCC easyblock
        """

        # environment variable may be defined but empty
        if os.getenv('MPICC', None) is None:
            raise EasyBuildError("Required environment variable %s not found (no toolchain used?).", envvar)

        # compilers
        extra_configopts = 'CC="%(mpicc)s" ' % {'mpicc': os.getenv('MPICC')}

        basedir = self.cfg['start_dir']
        if util:
            setupdir = os.path.join(basedir, 'darshan-util')
        else:
            setupdir = os.path.join(basedir, 'darshan-runtime')
            extra_configopts += '--with-mem-align=%(mem_align)s --with-log-path-by-env=%(logpath)s --with-jobid-env=%(jobid)s ' % {'mem_align' : self.cfg['mem_align'], 'logpath' : self.cfg['logpath_env'], 'jobid' : self.cfg['jobid_env']}

        try:
            os.chdir(setupdir)
        except OSError as err:
            raise EasyBuildError("Failed to change to to dir %s: %s", setupdir, err)

        # set options and build
        self.cfg.update('configopts', extra_configopts)
        super(EB_Darshan, self).configure_step()


    def install_step(self):
        """
        Custom install step for DARSHAN in order to install the utilities too
        """
        # make install darshan-runtime
        super(EB_Darshan, self).install_step()

        self.cfg['configopts'] = ''

        # compile darshan-util
        self.configure_step(util=True)
        #ConfigureMake.configure_step(self, util=True)
        super(EB_Darshan, self).build_step()
        super(EB_Darshan, self).install_step()


    def sanity_check_step(self):
        """
        Custom sanity check for Darshan
        """
        custom_paths = {
            'files' : [
                # darshan-runtime
                'bin/darshan-config', 'bin/darshan-gen-cc.pl',
                'bin/darshan-gen-cxx.pl', 'bin/darshan-gen-fortran.pl',
                'bin/darshan-mk-log-dirs.pl', 'lib/libdarshan.a',
                'lib/libdarshan.so',
                # darshan-util
                'bin/darshan-analyzer',
                'bin/darshan-convert',
                'bin/darshan-diff',
                'bin/darshan-dxt-parser',
                'bin/darshan-job-summary.pl',
                'bin/darshan-merge',
                'bin/darshan-parser',
                'bin/darshan-summary-per-file.sh',
                'bin/dxt_analyzer.py',
                'lib/libdarshan-util.a',
            ],
            'dirs'  : [ 'bin', 'lib', 'share' ],
        }

        super(EB_Darshan, self).sanity_check_step(custom_paths)


    def make_module_extra(self, *args, **kwargs):
        txt = super(EB_Darshan, self).make_module_extra(*args, **kwargs)

        if self.toolchain.toolchain_family() == toolchain.CRAYPE:
            txt += self.module_generator.prepend_paths('PE_PKGCONFIG_LIBS', 'darshan-runtime', expand_relpaths=False)

            #txt += self.module_generator.prepend_paths('PE_PKGCONFIG_LIBS', 'darshan-util', expand_relpaths=False)
            #txt += self.module_generator.prepend_paths('PE_PKGCONFIG_PRODUCTS', 'DARSHAN', expand_relpaths=False)
            #txt += self.module_generator.prepend_paths('DARSHAN_PKGCONFIG_LIBS', 'darshan', expand_relpaths=False)

        return txt
