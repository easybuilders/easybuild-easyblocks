##
# Copyright 2020-2021 Ghent University
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
EasyBuild support for building and installing PyTorch, implemented as an easyblock

@author: Alexander Grund (TU Dresden)
"""

import os
import re
import tempfile
from distutils.version import LooseVersion
from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
import easybuild.tools.environment as env
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.systemtools import POWER, get_cpu_architecture
from easybuild.tools.filetools import symlink, apply_regex_substitutions


class EB_PyTorch(PythonPackage):
    """Support for building/installing TensorFlow."""

    @staticmethod
    def extra_options():
        extra_vars = PythonPackage.extra_options()
        extra_vars.update({
            'excluded_tests': [{}, 'Mapping of architecture strings to list of tests to be excluded', CUSTOM],
            'custom_opts': [[], 'List of options for the build/install command. Can be used to change the defaults ' +
                                'set by the PyTorch EasyBlock, for example ["USE_MKLDNN=0"].', CUSTOM],
        })
        extra_vars['download_dep_fail'][0] = True
        extra_vars['sanity_pip_check'][0] = True

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Constructor for PyTorch easyblock."""
        super(EB_PyTorch, self).__init__(*args, **kwargs)
        self.options['modulename'] = 'torch'
        # Test as-if pytorch was installed
        self.testinstall = True
        self.tmpdir = tempfile.mkdtemp(suffix='-pytorch-build')

    def fetch_step(self, skip_checksums=False):
        """Fetch sources for installing PyTorch, including those for tests."""
        super(EB_PyTorch, self).fetch_step(skip_checksums)
        # Resolve tests early to avoid failures later. Use obtain_file if path is not absolute
        tests = [test if os.path.isabs(test) else self.obtain_file(test) for test in self.cfg['tests']]
        self.cfg['tests'] = tests

    @staticmethod
    def get_dependency_options_for_version(pytorch_version):
        """
        PyTorch can enable some functionality based on available software or use system software instead of a submodule
        This returns EasyBuild names of that and the flag that should be used when the dependency is found

        The result is a list of tuples (enable_flag, eb_name)
        """
        pytorch_version = LooseVersion(pytorch_version)

        def is_version_ok(version_range):
            """Return True if the PyTorch version to be installed matches the version_range"""
            min_version, max_version = version_range.split(':')
            result = True
            if min_version and pytorch_version < LooseVersion(min_version):
                result = False
            if max_version and pytorch_version >= LooseVersion(max_version):
                result = False
            return result

        available_libs = (
            # Format: (PyTorch flag to enable, EB name, '<min version>:<exclusive max version>')
            # Use `None` for the EB name if no known EC exists
            ('USE_FFMPEG=1', 'FFmpeg', '1.0.0:'),
            ('USE_GFLAGS=1', 'gflags', '1.0.0:'),
            ('USE_GLOG=1', 'glog', '1.0.0:'),

            # For system libs check CMakeLists.txt, below `if(USE_SYSTEM_LIBS)`, order kept here
            # NCCL handled specially as other env variables are requires for it
            ('USE_SYSTEM_CPUINFO=1', None, '1.6.0:'),
            ('USE_SYSTEM_SLEEF=1', None, '1.6.0:'),
            ('USE_SYSTEM_GLOO=1', None, '1.6.0:'),
            ('BUILD_CUSTOM_PROTOBUF=0', 'protobuf', '1.2.0:'),
            ('USE_SYSTEM_EIGEN_INSTALL=1', 'Eigen', '1.0.0:'),
            ('USE_SYSTEM_FP16=1', None, '1.6.0:'),
            ('USE_SYSTEM_PTHREADPOOL=1', None, '1.6.0:'),
            ('USE_SYSTEM_PSIMD=1', None, '1.6.0:'),
            ('USE_SYSTEM_FXDIV=1', None, '1.6.0:'),
            ('USE_SYSTEM_BENCHMARK=1', None, '1.6.0:'),  # Google Benchmark
            ('USE_SYSTEM_ONNX=1', None, '1.6.0:'),
            ('USE_SYSTEM_XNNPACK=1', None, '1.6.0:'),
        )
        return [(enable_opt, dep_name) for enable_opt, dep_name, version_range in available_libs
                if is_version_ok(version_range)]

    def prepare_step(self, *args, **kwargs):
        """Make sure that versioned CMake alias exists"""
        super(EB_PyTorch, self).prepare_step(*args, **kwargs)
        # PyTorch preferes cmake3 over cmake which usually does not exist
        cmake_root = get_software_root('CMake')
        cmake_version = get_software_version('CMake')
        if cmake_root and not os.path.isfile(os.path.join(cmake_root, 'bin', 'cmake3')):
            if cmake_version and cmake_version.split('.')[0] != '3':
                raise EasyBuildError('PyTorch requires CMake 3 but CMake %s was found', cmake_version)
            cmake_bin_dir = tempfile.mkdtemp(suffix='cmake-bin')
            self.log.warning('Creating symlink `cmake3` in %s to avoid PyTorch picking up a system CMake. ' +
                             'Reinstall the CMake module to avoid this!', cmake_bin_dir)
            symlink(os.path.join(cmake_root, 'bin', 'cmake'), os.path.join(cmake_bin_dir, 'cmake3'))
            path = "%s:%s" % (cmake_bin_dir, os.getenv('PATH'))
            env.setvar('PATH', path)

    def configure_step(self):
        """Custom configure procedure for PyTorch."""
        super(EB_PyTorch, self).configure_step()

        # Gather default options. Will be checked against (and can be overwritten by) custom_opts
        options = ['PYTORCH_BUILD_VERSION=' + self.version, 'PYTORCH_BUILD_NUMBER=1']

        # enable verbose mode when --debug is used (to show compiler commands)
        if build_option('debug'):
            options.append('VERBOSE=1')

        # Restrict parallelism
        options.append('MAX_JOBS=%s' % self.cfg['parallel'])

        # BLAS Interface
        if get_software_root('imkl'):
            options.append('BLAS=MKL')
            options.append('INTEL_MKL_DIR=$MKLROOT')
        elif LooseVersion(self.version) >= LooseVersion('1.9.0') and get_software_root('BLIS'):
            options.append('BLAS=BLIS')
            options.append('BLIS_HOME=' + get_software_root('BLIS'))
            options.append('USE_MKLDNN_CBLAS=ON')
        elif get_software_root('OpenBLAS'):
            # This is what PyTorch defaults to if no MKL is found.
            # Make this explicit here to avoid it finding MKL from the system
            options.append('BLAS=Eigen')
            # Still need to set a BLAS lib to use.
            # Valid choices: mkl/open/goto/acml/atlas/accelerate/veclib/generic (+blis for 1.9+)
            options.append('WITH_BLAS=open')
            # Make sure this option is actually passed to CMake
            apply_regex_substitutions(os.path.join('tools', 'setup_helpers', 'cmake.py'), [
                ("'BLAS',", "'BLAS', 'WITH_BLAS',")
            ])
        else:
            raise EasyBuildError("Did not find a supported BLAS in dependencies. Don't know which BLAS lib to use")

        available_dependency_options = EB_PyTorch.get_dependency_options_for_version(self.version)
        dependency_names = set(dep['name'] for dep in self.cfg.dependencies())
        not_used_dep_names = []
        for enable_opt, dep_name in available_dependency_options:
            if dep_name is None:
                continue
            if dep_name in dependency_names:
                options.append(enable_opt)
            else:
                not_used_dep_names.append(dep_name)
        self.log.info('Did not enable options for the following dependencies as they are not used in the EC: %s',
                      not_used_dep_names)

        # Use Infiniband by default
        # you can disable this by including 'USE_IBVERBS=0' in 'custom_opts' in the easyconfig file
        options.append('USE_IBVERBS=1')

        if get_software_root('CUDA'):
            options.append('USE_CUDA=1')
            cudnn_root = get_software_root('cuDNN')
            if cudnn_root:
                options.append('CUDNN_LIB_DIR=' + os.path.join(cudnn_root, 'lib64'))
                options.append('CUDNN_INCLUDE_DIR=' + os.path.join(cudnn_root, 'include'))

            nccl_root = get_software_root('NCCL')
            if nccl_root:
                options.append('USE_SYSTEM_NCCL=1')
                options.append('NCCL_INCLUDE_DIR=' + os.path.join(nccl_root, 'include'))

            # list of CUDA compute capabilities to use can be specifed in two ways (where (2) overrules (1)):
            # (1) in the easyconfig file, via the custom cuda_compute_capabilities;
            # (2) in the EasyBuild configuration, via --cuda-compute-capabilities configuration option;
            cuda_cc = build_option('cuda_compute_capabilities') or self.cfg['cuda_compute_capabilities']
            if not cuda_cc:
                raise EasyBuildError('List of CUDA compute capabilities must be specified, either via '
                                     'cuda_compute_capabilities easyconfig parameter or via '
                                     '--cuda-compute-capabilities')

            self.log.info('Compiling with specified list of CUDA compute capabilities: %s', ', '.join(cuda_cc))
            # This variable is also used at runtime (e.g. for tests) and if it is not set PyTorch will automatically
            # determine the compute capability of a GPU in the system and use that which may fail tests if
            # it is to new for the used nvcc
            env.setvar('TORCH_CUDA_ARCH_LIST', ';'.join(cuda_cc))
        else:
            # Disable CUDA
            options.append('USE_CUDA=0')

        if get_cpu_architecture() == POWER:
            # *NNPACK is not supported on Power, disable to avoid warnings
            options.extend(['USE_NNPACK=0', 'USE_QNNPACK=0', 'USE_PYTORCH_QNNPACK=0', 'USE_XNNPACK=0'])

        # Metal only supported on IOS which likely doesn't work with EB, so disabled
        options.append('USE_METAL=0')

        unique_options = self.cfg['custom_opts']
        for option in options:
            name = option.split('=')[0] + '='  # Include the equals sign to avoid partial matches
            if not any(opt.startswith(name) for opt in unique_options):
                unique_options.append(option)

        self.cfg.update('prebuildopts', ' '.join(unique_options) + ' ')
        self.cfg.update('preinstallopts', ' '.join(unique_options) + ' ')

    def test_step(self):
        """Run unit tests"""
        # Make PyTorch tests not use the user home
        env.setvar('XDG_CACHE_HOME', os.path.join(self.tmpdir, '.cache'))
        # Pretend to be on FB CI which disables some tests, especially those which download stuff
        env.setvar('SANDCASTLE', '1')
        # Skip this test(s) which is very flaky
        env.setvar('SKIP_TEST_BOTTLENECK', '1')
        # Parse excluded_tests and flatten into space separated string
        excluded_tests = []
        for arch, tests in self.cfg['excluded_tests'].items():
            if not arch or arch == get_cpu_architecture():
                excluded_tests.extend(tests)
        # -x should not be used if there are no excluded tests
        if excluded_tests:
            excluded_tests = ['-x'] + excluded_tests
        self.cfg.template_values.update({
            'python': self.python_cmd,
            'excluded_tests': ' '.join(excluded_tests)
        })
        super(EB_PyTorch, self).test_step()

    def test_cases_step(self):
        # Make PyTorch tests not use the user home
        env.setvar('XDG_CACHE_HOME', os.path.join(self.tmpdir, '.cache'))
        super(EB_PyTorch, self).test_cases_step()

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for PyTorch"""

        if self.cfg.get('download_dep_fail', True):
            # CMake might mistakenly download dependencies during configure
            self.log.info('Checking for downloaded submodules')
            pattern = r'^-- Downloading (\w+) to /'
            downloaded_deps = re.findall(pattern, self.install_cmd_output, re.M)

            if downloaded_deps:
                self.log.info('Found downloaded submodules: %s', ', '.join(downloaded_deps))
                fail_msg = 'found one or more downloaded dependencies: %s' % ', '.join(downloaded_deps)
                self.sanity_check_fail_msgs.append(fail_msg)

        super(EB_PyTorch, self).sanity_check_step(*args, **kwargs)

    def make_module_req_guess(self):
        """Set extra environment variables for PyTorch."""

        guesses = super(EB_PyTorch, self).make_module_req_guess()
        guesses['CMAKE_PREFIX_PATH'] = [os.path.join(self.pylibdir, 'torch')]
        # Required to dynamically load libcaffe2_nvrtc.so
        guesses['LD_LIBRARY_PATH'] = [os.path.join(self.pylibdir, 'torch', 'lib')]
        return guesses
