##
# Copyright 2015-2020 Ghent University
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
EasyBuild support for building and installing Xmipp, implemented as an easyblock

@author: Jens Timmerman (Ghent University)
@author: Pablo Escobar (sciCORE, SIB, University of Basel)
@author: Kenneth Hoste (Ghent University)
@author: Ake Sandgren (HPC2N, Umea University)
"""
import glob
import os

import easybuild.tools.environment as env
from distutils.version import LooseVersion
from easybuild.easyblocks.generic.scons import SCons
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions, change_dir
from easybuild.tools.filetools import copy_file, mkdir, remove_file, symlink
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_Xmipp(SCons):
    """Support for building/installing Xmipp."""

    def __init__(self, *args, **kwargs):
        """Initialize Xmipp-specific variables."""
        super(EB_Xmipp, self).__init__(*args, **kwargs)
        self.xmipp_modules = ['xmippCore', 'xmipp', 'xmippViz']
        self.srcdir = os.path.join(self.builddir, 'src')
        self.cfg['start_dir'] = self.builddir
        self.use_cuda = False
        self.cfgfile = os.path.join(self.builddir, 'xmipp.conf')

    def extract_step(self):
        """Extract Xmipp sources."""
        # Xmipp assumes that everything is unpacked in a "src" dir
        mkdir(self.srcdir)
        self.cfg.update('unpack_options', '--directory %s' % os.path.basename(self.srcdir))
        super(EB_Xmipp, self).extract_step()
        for module in self.xmipp_modules:
            symlink('%s-%s' % (module, self.version), os.path.join(self.srcdir, module), use_abspath_source=False)

    def patch_step(self):
        """Patch files from self.srcdir dir."""
        super(EB_Xmipp, self).patch_step(beginpath=self.srcdir)

    def setup_xmipp_env(self):
        """Setup environment before running SCons."""
        env.setvar('LINKERFORPROGRAMS', os.environ['CXX'])
        env.setvar('MPI_CC', os.getenv('MPICC'))
        env.setvar('MPI_CXX', os.getenv('MPICXX'))
        env.setvar('MPI_LINKERFORPROGRAMS', os.getenv('MPICXX'))
        incpath = os.path.join(get_software_root('Java'), 'include')
        env.setvar('JNI_CPPPATH', os.pathsep.join([incpath, os.path.join(incpath, 'linux')]))
        env.setvar('JAVAC', 'javac')
        env.setvar('JAR', 'jar')

    def configure_step(self):
        """Custom configuration procedure for Xmipp."""

        # Tell xmipp config that there is no Scipion.
        env.setvar('XMIPP_NOSCIPION', 'True')
        # Initialize the config file and then patch it with the correct values
        cmd = ' '.join([
            self.cfg['preconfigopts'],
            os.path.join(self.srcdir, 'xmipp', 'xmipp'),
            'config',
            self.cfg['configopts'],
        ])
        run_cmd(cmd, log_all=True, simple=True)

        # Parameters to be set in the config file
        params = {
            'CC': os.environ['CC'],
            'CXX': os.environ['CXX'],
            'LINKERFORPROGRAMS': os.environ['CXX'],
            'LIBDIRFLAGS': '',
            # I don't think Xmipp can actually build without MPI.
            'MPI_CC': os.environ.get('MPICC', 'UNKNOWN'),
            'MPI_CXX': os.environ.get('MPICXX', 'UNKNOWN'),
            'MPI_LINKERFORPROGRAMS': os.environ.get('MPICXX', 'UNKNOWN'),
        }

        deps = [
            # Name of dependency, name of env var to set, required or not
            ('HDF5', None, True),
            ('SQLite', None, True),
            ('LibTIFF', None, True),
            ('libjpeg-turbo', None, True),
            ('Java', 'JAVA_HOME', True),
            ('MATLAB', 'MATLAB_DIR', False),
        ]

        cuda_root = get_software_root('CUDA')
        if cuda_root:
            params.update({'CUDA_BIN': os.path.join(cuda_root, 'bin')})
            params.update({'CUDA_LIB': os.path.join(cuda_root, 'lib64')})
            params.update({'NVCC': os.environ['CUDA_CXX']})
            # Their default for NVCC is to use g++-5, fix that
            nvcc_flags = '--x cu -D_FORCE_INLINES -Xcompiler -fPIC '
            nvcc_flags = nvcc_flags + '-Wno-deprecated-gpu-targets -std=c++11'
            params.update({'NVCC_CXXFLAGS': nvcc_flags})
            self.use_cuda = True

            # Make sure cuFFTAdvisor is available even if unpacked under
            # a different name
            if not os.path.isdir('cuFFTAdvisor'):
                matches = glob.glob(os.path.join(self.srcdir, 'cuFFTAdvisor-*'))
                if len(matches) == 1:
                    cufft = os.path.basename(matches[0])
                    symlink(cufft, os.path.join(self.srcdir, 'cuFFTAdvisor'), use_abspath_source=False)
                else:
                    raise EasyBuildError("Failed to isolate path to cuFFTAdvisor-*: %s", matches)

        for dep in ['CUDA', 'MATLAB']:
            use_dep = bool(get_software_root(dep))
            params.update({dep: use_dep})

        if get_software_root('OpenCV'):
            params.update({'OPENCV': True})
            if self.use_cuda:
                params.update({'OPENCVSUPPORTSCUDA': True})
            if LooseVersion(get_software_version('OpenCV')) >= LooseVersion('3'):
                params.update({'OPENCV3': True})

        missing_deps = []
        for dep, var, required in deps:
            root = get_software_root(dep)
            if root:
                if var:
                    params.update({var: root})
            elif required:
                missing_deps.append(dep)

        if missing_deps:
            raise EasyBuildError("One or more required dependencies not available: %s", ', '.join(missing_deps))

        # Here we know that Java exists since it is a required dependency
        jnipath = os.path.join(get_software_root('Java'), 'include')
        jnipath = os.pathsep.join([jnipath, os.path.join(jnipath, 'linux')])
        params.update({'JNI_CPPPATH': jnipath})

        regex_subs = []

        # Set the variables in the config file to match the environment from EasyBuild
        for (key, val) in params.items():
            regex_subs.extend([(r'^%s\s*=.*$' % key, r'%s = %s' % (key, val))])

        apply_regex_substitutions(self.cfgfile, regex_subs)

        self.setup_xmipp_env()

        py_ver = get_software_version('Python')
        py_maj_ver = LooseVersion(py_ver).version[0]
        py_min_ver = LooseVersion(py_ver).version[1]
        pyver = 'python%s.%s' % (py_maj_ver, py_min_ver)
        pyincpath = os.path.join(get_software_root('Python'), 'include', pyver)
        # Temp workaround for missing include/pythonx.y in CPATH
        env.setvar('CPATH', os.pathsep.join([os.environ['CPATH'], pyincpath]))

        super(EB_Xmipp, self).configure_step()

    def build_step(self):
        """Custom build step for Xmipp."""

        # First build cuFFTAdvisor, XmippCore depends on this when CUDA is enabled.
        if self.use_cuda:
            cwd = change_dir(os.path.join(self.srcdir, 'cuFFTAdvisor'))
            cmd = ' '.join([
                self.cfg['prebuildopts'],
                'make',
                'all',
                self.cfg['buildopts'],
            ])
            run_cmd(cmd, log_all=True, simple=True)
            change_dir(cwd)
            xmipp_lib = os.path.join(self.srcdir, 'xmipp', 'lib')
            mkdir(xmipp_lib)
            shlib_ext = get_shared_lib_ext()
            libname = 'libcuFFTAdvisor.%s' % shlib_ext
            copy_file(os.path.join(self.srcdir, 'cuFFTAdvisor', 'build', libname), xmipp_lib)

        self.cfg.update('buildopts', '--verbose')
        for module in self.xmipp_modules:
            moddir = os.path.join(os.path.basename(self.srcdir), module)
            symlink(self.cfgfile, os.path.join(self.srcdir, module, 'install', 'xmipp.conf'))
            cwd = change_dir(moddir)
            super(EB_Xmipp, self).build_step()
            change_dir(cwd)

    def install_step(self):
        """Custom install step for Xmipp."""

        # Use the xmipp script to do the install, there's too much
        # to replicate here.
        cmd = ' '.join([
            self.cfg['preinstallopts'],
            os.path.join(self.srcdir, 'xmipp', 'xmipp'),
            'install',
            self.installdir,
            self.cfg['installopts'],
        ])
        run_cmd(cmd, log_all=True, simple=True)

        # Remove the bash and fish files. Everything should be in the module
        remove_file(os.path.join(self.installdir, 'xmipp.bashrc'))
        remove_file(os.path.join(self.installdir, 'xmipp.fish'))

    def sanity_check_step(self):
        """Custom sanity check for Xmipp."""

        shlib_ext = get_shared_lib_ext()

        bins = ['xmipp_%s' % x for x in ['angular_rotate', 'classify_kerdensom', 'mpi_ml_refine3d']]
        libs = ['XmippCore', 'XmippJNI', 'XmippParallel', 'Xmipp']
        custom_paths = {
            'files': [os.path.join('bin', x) for x in bins] +
            [os.path.join('bindings', 'python', 'xmippViz.py')] +
            [os.path.join('lib', 'lib%s.%s') % (x, shlib_ext) for x in libs],
            'dirs': ['resources'],
        }
        return super(EB_Xmipp, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Set the install directory as XMIPP_HOME"""
        txt = super(EB_Xmipp, self).make_module_extra()
        txt += self.module_generator.set_environment('XMIPP_HOME', self.installdir)
        self.log.debug("make_module_extra added this: %s", txt)
        return txt

    def make_module_req_guess(self):
        """Custom guesses for environment variables for Xmipp."""
        guesses = super(EB_Xmipp, self).make_module_req_guess()
        guesses.update({
            'LD_LIBRARY_PATH': ['lib', os.path.join('bindings', 'python')],
            'PYTHONPATH': [os.path.join('bindings', 'python'), 'pylib'],
        })
        return guesses
