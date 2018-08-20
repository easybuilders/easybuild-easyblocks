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

@author: Kenneth Hoste (Ghent University)
@author: Ake Sandgren (HPC2N, Umea University)
"""
import os

import easybuild.tools.environment as env
from distutils.version import LooseVersion
from easybuild.easyblocks.generic.scons import SCons
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, mkdir, symlink
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd


class EB_Scipion(SCons):
    """Support for building/installing Scipion."""

    def __init__(self, *args, **kwargs):
        """Initialize Scipion-specific variables."""
        super(EB_Scipion, self).__init__(*args, **kwargs)
        self.build_in_installdir = True

        # scipion.cfg file
        self.cfgdir = os.path.join(self.cfg['start_dir'], 'config')
        self.cfgfile = os.path.join(self.cfgdir, 'scipion.conf')

    def extract_step(self):
        """Extract Scipion sources."""
        # strip off 'scipion-*' part to avoid having everything in a subdirectory
        self.cfg.update('unpack_options', '--strip-components=1')
        super(EB_Scipion, self).extract_step()

    def setup_scipion_env(self):
        # Need to setup some environment variables before running SCons
        env.setvar('SCIPION_HOME', self.installdir)
        env.setvar('SCIPION_CWD', self.builddir)
        env.setvar('SCIPION_VERSION', self.version)
        env.setvar('SCIPION_CONFIG', self.cfgfile)
        env.setvar('SCIPION_LOCAL_CONFIG', self.cfgfile)
        env.setvar('SCIPION_PROTOCOLS', os.path.join(self.cfgdir, 'protocols.conf'))
        env.setvar('SCIPION_HOSTS', os.path.join(self.cfgdir, 'hosts.conf'))
        # TODO: read this from scipion.conf
        env.setvar('SCIPION_URL_SOFTWARE', 'http://scipion.cnb.csic.es/downloads/scipion/software')
        env.setvar('LINKERFORPROGRAMS', os.environ['CXX'])
        env.setvar('MPI_CC', os.getenv('MPICC'))
        env.setvar('MPI_CXX', os.getenv('MPICXX'))
        env.setvar('MPI_LINKERFORPROGRAMS', os.getenv('MPICXX'))
        incpath = os.path.join(get_software_root('Java'), 'include')
        env.setvar('JNI_CPPPATH', os.pathsep.join([incpath, os.path.join(incpath, 'linux')]))
        env.setvar('JAVAC', 'javac')
        env.setvar('JAR', 'jar')

    def configure_step(self):
        """Custom configuration procedure for Scipion."""
        # Setup scipion.conf, protocols.conf, and host.conf
        # scipion.conf needs to be configured with paths to all the
        # dependencies, stupid but that's the way it works at the
        # moment.

        # Create the config files and then make the subtitutions
        cmd = './scipion --config %s config' % self.cfgfile
        run_cmd(cmd, log_all=True, simple=True)

        params = {
            'CC': os.environ['CC'],
            'CXX': os.environ['CXX'],
            'LINKERFORPROGRAMS': os.environ['CXX'],
            # I don't think Scipion can actually build without MPI.
            'MPI_CC': os.environ.get('MPICC', 'UNKNOWN'),
            'MPI_CXX': os.environ.get('MPICXX', 'UNKNOWN'),
            'MPI_LINKERFORPROGRAMS': os.environ.get('MPICXX', 'UNKNOWN'),
            # Set MPI_LIBDIR/INCLUDE/BINDIR to dummy values.
            # Makes it easier to detect if they are still misused someplace.
            # To be removed or changed to the real values later...
            'MPI_LIBDIR': '/dummy',
            'MPI_INCLUDE': '/dummy',
            'MPI_BINDIR': '/dummy',
        }

        deps = [
            # dep name, is required dep?
            ('EMAN2', 'EMAN2DIR', False),
            ('frealign', 'FREALIGN_HOME', False),
            ('Java', 'JAVA_HOME', True),
            ('MATLAB', 'MATLAB_DIR', False),
            ('MotionCor2', 'MOTIONCOR2_HOME', False),
            ('RELION', 'RELION_HOME', False),
            ('VMD', 'VMD_HOME', False),
        ]

        regex_subs = []

        if get_software_root('ctffind'):
            # note: check whether ctffind 4.x is being used
            if LooseVersion(get_software_version('ctffind')).version[0] == 4:
                deps.append(('ctffind', 'CTFFIND4_HOME', False))
            else:
                deps.append(('ctffind', 'CTFFIND_HOME', False))

        cuda_root = get_software_root('CUDA')
        if cuda_root:
            params.update({'CUDA_BIN': '%s' % os.path.join(cuda_root, 'bin')})
            params.update({'(.*CUDA_LIB)': '%s' % os.path.join(cuda_root, 'lib64')})
        for dep in ['CUDA', 'MATLAB', 'OpenCV']:
            use_dep = bool(get_software_root(dep))
            params.update({dep: use_dep})

        if get_software_root('MotionCor2'):
            # The EB motioncor2 build links the binary to an explicit name
            params.update({'MOTIONCOR2_BIN': 'motioncor2'})

        missing_deps = []
        for dep, var, required in deps:
            root = get_software_root(dep)
            if root:
                params.update({var: root})
            elif required:
                missing_deps.append(dep)

        if missing_deps:
            raise EasyBuildError("One or more required dependencies not available: %s", ', '.join(missing_deps))

        # Here we know that Java exists since it is a required dependency
        jnipath = os.path.join(get_software_root('Java'), 'include')
        jnipath = os.pathsep.join([jnipath, os.path.join(jnipath, 'linux')])
        params.update({'JNI_CPPPATH': jnipath})

        for (key, val) in params.items():
            regex_subs.extend([(r'^%s\s*=.*$' % key, r'%s = %s' % (key, val))])

        apply_regex_substitutions(self.cfgfile, regex_subs)

        self.setup_scipion_env()

    def install_step(self):
        """Custom install step for Scipion."""

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
            'files': ['scipion', os.path.join('software', 'em', 'xmipp', 'bin', 'xmipp_volume_validate_pca')],
            'dirs': ['scripts'],
        }
        super(EB_Scipion, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """Custom guesses for environment variables (PATH, ...) for Scipion."""
        guesses = super(EB_Scipion, self).make_module_req_guess()
        guesses.update({'PATH': ['scripts']})
        return guesses
