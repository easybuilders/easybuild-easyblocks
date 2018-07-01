##
# Copyright 2018 Ghent University
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
EasyBuild support for building and installing Scipion, implemented as an easyblock

@author: Ake Sandgren (HPC2N, Umea University)
"""
import glob
import os
import re
import shutil

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.scons import SCons
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, mkdir, symlink
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd

class EB_Scipion(SCons):
    """Support for building/installing Scipion."""

    def __init__(self, *args, **kwargs):
        """Initialize Scipion-specific variables."""
        super(EB_Scipion, self).__init__(*args, **kwargs)

    def configure_step(self):
        """Custom configuration procedure for Scipion."""
        # Setup scipion.conf, protocols.conf, and host.conf
        # scipion.conf needs to be configured with paths to all the
        # dependencies, stupid but that's the way it works at the
        # moment.

        # Create the config files and then make the subtitutions
        cmd = './scipion --config %s/config/scipion.conf config' % self.installdir
        run_cmd(cmd, log_all=True, simple=True)

        # Mapping of EB software names and variables to patch in
        # scipion.conf
        map_sw2var_name = {
            'ctffind': 'CTFFIND4_HOME',
            'EMAN2': 'EMAN2DIR',
            'frealign': 'FREALIGN_HOME',
            'MotionCor2': 'MOTIONCOR2_HOME',
            'RELION': 'RELION_HOME',
            'Java': 'JAVA_HOME',
            'VMD': 'VMD_HOME',
            'MATLAB': 'MATLAB_DIR',
        }

        # Some other variables we need to change
        regex_subs = [
            (r'^CC = .*$', r'CC = %s' % os.getenv('CC')),
            (r'^CXX = .*$', r'CXX = %s' % os.getenv('CXX')),
            (r'^LINKERFORPROGRAMS = .*$', r'LINKERFORPROGRAMS = %s' % os.getenv('CXX')),
            (r'^MPI_CC = .*$', r'MPI_CC = %s' % os.getenv('MPICC')),
            (r'^MPI_CXX = .*$', r'MPI_CXX = %s' % os.getenv('MPICXX')),
            (r'^MPI_LINKERFORPROGRAMS = .*$', r'MPI_LINKERFORPROGRAMS = %s' % os.getenv('MPICXX')),
            (r'^MPI_LIBDIR = .*$', r'MPI_LIBDIR = /'),
            (r'^MPI_INCLUDE = .*$', r'MPI_INCLUDE = /'),
            (r'^MPI_BINDIR = .*$', r'MPI_BINDIR = /'),
            # The EB motioncor2 build renames that binary to an explicit name
            (r'^MOTIONCOR2_BIN = .*$', r'MOTIONCOR2_BIN = motioncor2'),
        ]
        for (k, v) in map_sw2var_name.items():
            swroot = get_software_root(k)
            if swroot:
                regex_subs.extend([(r'^%s = .*$' % v, r'%s = %s' % (v, swroot))])
        cuda_root = get_software_root('CUDA')
        if cuda_root:
            regex_subs.extend([(r'^(.*CUDA_LIB) = .*$', r'\1 = %s/lib64' % (cuda_root))])
            regex_subs.extend([(r'^CUDA_BIN = .*$', r'CUDA_BIN = %s/bin' % (cuda_root))])
            regex_subs.extend([(r'^CUDA = .*$', r'CUDA = True')])

        java_root = get_software_root('Java')
        if java_root:
            jnipath = os.path.join(java_root, 'include')
            jnipath = os.pathsep.join([jnipath, os.path.join(jnipath, 'linux')])
            regex_subs.extend([(r'^JNI_CPPPATH = .*$', r'JNI_CPPPATH = %s' % jnipath)])

        if get_software_root('OpenCV'):
            opencv = 'True'
        else:
            opencv = 'False'
        regex_subs.extend([(r'^OPENCV = .*$', r'OPENCV = %s' % opencv)])

        if get_software_root('MATLAB'):
            matlab = 'True'
        else:
            matlab = 'False'
        regex_subs.extend([(r'^MATLAB = .*$', r'MATLAB = %s' % matlab)])

        apply_regex_substitutions('%s/config/scipion.conf' % self.installdir, regex_subs)

    def setup_env(self):
        # Need to setup some environemt variables before running SCons
        env.setvar('SCIPION_HOME', self.installdir)
        env.setvar('SCIPION_CWD', self.builddir)
        env.setvar('SCIPION_VERSION', self.version)
        env.setvar('SCIPION_CONFIG', '%s/config/scipion.conf' % self.installdir)
        env.setvar('SCIPION_LOCAL_CONFIG', '%s/config/scipion.conf' % self.installdir)
        env.setvar('SCIPION_PROTOCOLS', '%s/config/protocols.conf' % self.installdir)
        env.setvar('SCIPION_HOSTS', '%s/config/hosts.conf' % self.installdir)
        # Read this from scipion.conf
        env.setvar('SCIPION_URL_SOFTWARE', 'http://scipion.cnb.csic.es/downloads/scipion/software')
        env.setvar('LINKERFORPROGRAMS', os.getenv('CXX'))
        env.setvar('MPI_CC', os.getenv('MPICC'))
        env.setvar('MPI_CXX', os.getenv('MPICXX'))
        env.setvar('MPI_LINKERFORPROGRAMS', os.getenv('MPICXX'))
        java_root = get_software_root('Java')
        env.setvar('JNI_CPPPATH', '%s/include:%s/include/linux' % (java_root, java_root))
        env.setvar('JAVAC', 'javac')
        env.setvar('JAR', 'jar')

    def build_step(self):
        """Custom build step for Scipion."""
        self.setup_env()

        super(EB_Scipion, self).build_step()

    def install_step(self):
        """Custom install step for Scipion."""
        self.setup_env()

        super(EB_Scipion, self).install_step()

        # Scipion needs this directory created to put examples in when
        # running tests.
        datadir = os.path.join(self.installdir, 'data', 'tests')
        mkdir(datadir, parents=True)

        # Add a bin dir and a link to scipion
        bindir = os.path.join(self.installdir, 'bin')
        mkdir(bindir)
        cwd = change_dir(bindir)
        symlink(os.path.join('..', 'scipion'), 'scipion', use_abspath_source=False)
        change_dir(cwd)

    def sanity_check_step(self):
        """Custom sanity check for Scipion."""

        custom_paths = {
            'files': ['software/em/xmipp/bin/xmipp_volume_validate_pca'],
            'dirs': [],
        }
        super(EB_Scipion, self).sanity_check_step(custom_paths=custom_paths)
