##
# Copyright 2019-2024 Ghent University
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

@author: Kenneth Hoste (Ghent University)
@author: Ake Sandgren (HPC2N, Umea University)
"""
import os

from easybuild.tools import LooseVersion
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy, mkdir, symlink
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.py2vs3 import configparser
from easybuild.tools.run import run_cmd


class EB_Scipion(ExtensionEasyBlock):
    """Support for building/installing Scipion."""

    def __init__(self, *args, **kwargs):
        """Initialize Scipion-specific variables."""
        super(EB_Scipion, self).__init__(*args, **kwargs)
        # strip off 'scipion-*' part to avoid having everything in a subdirectory
        self.unpack_options = '--strip-components=1'

    def configure_step(self):
        """Custom configuration procedure for Scipion."""
        # Setup scipion.conf, protocols.conf, and host.conf
        # scipion.conf needs to be configured with paths to all the
        # dependencies, stupid but that's the way it works at the
        # moment.

        cfgfile = os.path.join(self.builddir, 'config', 'scipion.conf')

        # Create the config files and then make the subtitutions
        cmd = ' '.join([
            self.cfg['preconfigopts'],
            './scipion',
            '--config',
            cfgfile,
            'config',
            self.cfg['configopts'],
        ])
        run_cmd(cmd, log_all=True, simple=True)

        # Things that go into the BUILD section of scipion.conf
        build_params = {
            'CC': os.environ['CC'],
            'CXX': os.environ['CXX'],
            'LINKERFORPROGRAMS': os.environ['CXX'],
            'MPI_CC': os.environ.get('MPICC', 'UNKNOWN'),
            'MPI_CXX': os.environ.get('MPICXX', 'UNKNOWN'),
            'MPI_LINKERFORPROGRAMS': os.environ.get('MPICXX', 'UNKNOWN'),
        }

        package_params = {
            # Some variables we can set regardless of whether it exists as a dependency or not.
            'GCTF': 'Gctf',
            'MOTIONCOR2_BIN': 'motioncor2',
            'NVCC_INCLUDE': '',
            'NVCC_LIBDIR': '',
        }

        # EM package dependencies and the corresponding scipion.conf variable
        deps = [
            # dep name, environment variable to define, is required dep?
            ('frealign', 'FREALIGN_HOME', False),
            ('Gctf', 'GCTF_HOME', False),
            ('MotionCor2', 'MOTIONCOR2_HOME', False),
            ('RELION', 'RELION_HOME', False),
            ('VMD', 'VMD_HOME', False),
            ('Xmipp', 'XMIPP_HOME', True),
        ]

        if LooseVersion(self.version) >= LooseVersion('2.0'):
            deps.append(('EMAN2', 'EMAN2_HOME', False))
        else:
            deps.append(('EMAN2', 'EMAN2DIR', False))

        if get_software_root('ctffind'):
            if LooseVersion(get_software_version('ctffind')) >= LooseVersion('4.0'):
                deps.append(('ctffind', 'CTFFIND4_HOME', False))
            else:
                deps.append(('ctffind', 'CTFFIND_HOME', False))

        cuda_root = get_software_root('CUDA')
        build_params.update({'CUDA': bool(cuda_root)})
        if cuda_root:
            build_params.update({'CUDA_BIN': os.path.join(cuda_root, 'bin')})
            build_params.update({'CUDA_LIB': os.path.join(cuda_root, 'lib64')})

        opencv_root = get_software_root('OpenCV')
        build_params.update({'OPENCV': bool(opencv_root)})
        if opencv_root:
            build_params.update({'OPENCV_VER': get_software_version('OpenCV')})

        matlab_root = get_software_root('MATLAB')
        build_params.update({'MATLAB': bool(matlab_root)})
        if matlab_root:
            build_params.update({'MATLAB_DIR': matlab_root})

        missing_deps = []

        java_root = get_software_root('Java')
        if not java_root:
            missing_deps.append('JAVA')

        for dep, var, required in deps:
            root = get_software_root(dep)
            if root:
                package_params.update({var: root})
            elif required:
                missing_deps.append(dep)

        if missing_deps:
            raise EasyBuildError("One or more required dependencies not available: %s", ', '.join(missing_deps))

        # Here we know that Java exists
        build_params.update({'JAVA_HOME': java_root})
        jnipath = os.path.join(java_root, 'include')
        jnipath = os.pathsep.join([jnipath, os.path.join(jnipath, 'linux')])
        build_params.update({'JNI_CPPPATH': jnipath})

        cf = configparser.ConfigParser()
        cf.optionxform = str  # keep case

        try:
            cf.read(cfgfile)
        except (IOError, OSError) as err:
            raise EasyBuildError("Failed to read %s: %s", cfgfile, err)

        # Update BUILD settings
        for key in build_params:
            cf.set('BUILD', key, build_params[key])

        # Add param stuff
        for key in package_params:
            cf.set('PACKAGES', key, package_params[key])

        try:
            cf.write(open(cfgfile, 'w'))
        except (IOError, OSError) as err:
            raise EasyBuildError("Failed to write %s: %s", cfgfile, err)

    def build_step(self):
        """No build step, this is pure python code"""
        pass

    def install_step(self):
        """Custom install step for Scipion."""

        copy(['config', 'pyworkflow', 'scipion', 'software'], self.installdir)
        datadir = os.path.join(self.installdir, 'data', 'tests')
        mkdir(datadir, parents=True)
        mkdir(os.path.join(self.installdir, 'bin'))
        linktarget = os.path.join(self.installdir, 'bin', 'scipion')
        symlink(os.path.join('..', 'scipion'), linktarget, use_abspath_source=False)

    def run(self, *args, **kwargs):
        """Perform the actual Scipion package configure/installation procedure"""

        # The ExtensionEasyBlock run does unpack and patch
        super(EB_Scipion, self).run(unpack_src=True)
        self.builddir = self.ext_dir

        # configure, build, install
        self.configure_step()
        self.build_step()
        self.install_step()

    def sanity_check_step(self):
        """Custom sanity check for Scipion."""

        custom_paths = {
            'files': [os.path.join('bin', 'scipion')],
            'dirs': ['config', 'data', 'pyworkflow', 'software'],
        }
        return super(EB_Scipion, self).sanity_check_step(custom_paths=custom_paths)
