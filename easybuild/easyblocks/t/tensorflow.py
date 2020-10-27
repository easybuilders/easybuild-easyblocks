##
# Copyright 2017-2020 Ghent University
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
EasyBuild support for building and installing TensorFlow, implemented as an easyblock

@author: Kenneth Hoste (HPC-UGent)
@author: Ake Sandgren (Umea University)
@author: Damian Alvarez (Forschungzentrum Juelich GmbH)
"""
import glob
import os
import re
import stat
import tempfile
import json
from distutils.version import LooseVersion

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.pythonpackage import PythonPackage, det_python_version
from easybuild.easyblocks.python import EXTS_FILTER_PYTHON_PACKAGES
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import run
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.filetools import adjust_permissions, apply_regex_substitutions, copy_file, mkdir, resolve_path
from easybuild.tools.filetools import is_readable, read_file, which, write_file, remove_file
from easybuild.tools.modules import get_software_root, get_software_version, get_software_libdir
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import X86_64, get_cpu_architecture, get_os_name, get_os_version
from easybuild.tools.py2vs3 import subprocess_popen_text


# Wrapper for Intel(MPI) compilers, where required environment variables
# are hardcoded to make sure they are present;
# this is required because Bazel resets the environment in which
# compiler commands are executed...
INTEL_COMPILER_WRAPPER = """#!/bin/bash

export CPATH='%(cpath)s'

# Only relevant for Intel compilers.
export INTEL_LICENSE_FILE='%(intel_license_file)s'

# Only relevant for MPI compiler wrapper (mpiicc/mpicc etc),
# not for regular compiler.
export I_MPI_ROOT='%(intel_mpi_root)s'

# Exclude location of this wrapper from $PATH to avoid other potential
# wrappers calling this wrapper.
export PATH=$(echo $PATH | tr ':' '\n' | grep -v "^%(wrapper_dir)s$" | tr '\n' ':')

%(compiler_path)s "$@"
"""


def split_tf_libs_txt(valid_libs_txt):
    """Split the VALID_LIBS entry from the TF file into single names"""
    entries = valid_libs_txt.split(',')
    # Remove double quotes and whitespace
    result = [entry.strip().strip('"') for entry in entries]
    # Remove potentially trailing empty element due to trailing comma in the txt
    if not result[-1]:
        result.pop()
    return result


def get_system_libs_from_tf(source_dir):
    """Return the valid values for TF_SYSTEM_LIBS from the TensorFlow source directory"""
    syslibs_path = os.path.join(source_dir, 'third_party', 'systemlibs', 'syslibs_configure.bzl')
    result = []
    if os.path.exists(syslibs_path):
        txt = read_file(syslibs_path)
        valid_libs_match = re.search(r'VALID_LIBS\s*=\s*\[(.*?)\]', txt, re.DOTALL)
        if not valid_libs_match:
            raise EasyBuildError('VALID_LIBS definition not found in %s', syslibs_path)
        result = split_tf_libs_txt(valid_libs_match.group(1))
    return result


def get_system_libs_for_version(tf_version, as_valid_libs=False):
    """
    Determine valid values for $TF_SYSTEM_LIBS for the given TF version

    If as_valid_libs=False (default) then returns 2 dictioniaries:
        1: Mapping of <EB name> to <TF name>
        2: Mapping of <package name> to <TF name> (for python extensions)
    else returns a string formated like the VALID_LIBS variable in third_party/systemlibs/syslibs_configure.bzl
        Those can be used to check/diff against third_party/systemlibs/syslibs_configure.bzl by running:
            python -c 'from easybuild.easyblocks.tensorflow import get_system_libs_for_version; \
                        print(get_system_libs_for_version("2.1.0", as_valid_libs=True))'
    """
    tf_version = LooseVersion(tf_version)

    def is_version_ok(version_range):
        """Return True if the TF version to be installed matches the version_range"""
        min_version, max_version = version_range.split(':')
        result = True
        if min_version and tf_version < LooseVersion(min_version):
            result = False
        if max_version and tf_version >= LooseVersion(max_version):
            result = False
        return result

    # For these lists check third_party/systemlibs/syslibs_configure.bzl --> VALID_LIBS
    # Also verify third_party/systemlibs/<name>.BUILD or third_party/systemlibs/<name>/BUILD.system
    # if it does something "strange" (e.g. link hardcoded headers)

    # Software which is added as a dependency in the EC
    available_system_libs = {
        # Format: (<EB name>, <version range>): <TF name>
        #         <version range> is '<min version>:<exclusive max version>'
        ('cURL', '2.0.0:'): 'curl',
        ('double-conversion', '2.0.0:'): 'double_conversion',
        ('flatbuffers', '2.0.0:'): 'flatbuffers',
        ('giflib', '2.0.0:2.1.0'): 'gif_archive',
        ('giflib', '2.1.0:'): 'gif',
        ('hwloc', '2.0.0:'): 'hwloc',
        ('ICU', '2.0.0:'): 'icu',
        ('JsonCpp', '2.0.0:'): 'jsoncpp_git',
        ('libjpeg-turbo', '2.0.0:2.2.0'): 'jpeg',
        ('libjpeg-turbo', '2.2.0:'): 'libjpeg_turbo',
        ('libpng', '2.0.0:2.1.0'): 'png_archive',
        ('libpng', '2.1.0:'): 'png',
        ('LMDB', '2.0.0:'): 'lmdb',
        ('NASM', '2.0.0:'): 'nasm',
        ('nsync', '2.0.0:'): 'nsync',
        ('PCRE', '2.0.0:'): 'pcre',
        ('protobuf-python', '2.0.0:'): 'com_google_protobuf',
        ('pybind11', '2.2.0:'): 'pybind11',
        ('snappy', '2.0.0:'): 'snappy',
        ('SQLite', '2.0.0:'): 'org_sqlite',
        ('SWIG', '2.0.0:'): 'swig',
        ('zlib', '2.0.0:2.2.0'): 'zlib_archive',
        ('zlib', '2.2.0:'): 'zlib',
    }
    # Software recognized by TF but which is always disabled (usually because no EC is known)
    # Format: <TF name>: <version range>
    unused_system_libs = {
        'boringssl': '2.0.0:',
        'com_github_googleapis_googleapis': '2.0.0:',
        'com_github_googlecloudplatform_google_cloud_cpp': '2.0.0:',  # Not used due to $TF_NEED_GCP=0
        'com_github_grpc_grpc': '2.2.0:',
        'com_googlesource_code_re2': '2.0.0:',
        'grpc': '2.0.0:2.2.0',
    }
    # Python packages installed as extensions or in the Python module
    # Will be checked for availabilitly
    # Format: (<package name>, <version range>): <TF name>
    python_system_libs = {
        ('absl', '2.0.0:'): 'absl_py',
        ('astor', '2.0.0:'): 'astor_archive',
        ('astunparse', '2.2.0:'): 'astunparse_archive',
        ('cython', '2.0.0:'): 'cython',  # Part of Python EC
        ('enum', '2.0.0:'): 'enum34_archive',  # Part of Python3
        ('functools', '2.0.0:'): 'functools32_archive',  # Part of Python3
        ('gast', '2.0.0:'): 'gast_archive',
        ('keras_applications', '2.0.0:2.2.0'): 'keras_applications_archive',
        ('opt_einsum', '2.0.0:'): 'opt_einsum_archive',
        ('pasta', '2.0.0:'): 'pasta',
        ('six', '2.0.0:'): 'six_archive',  # Part of Python EC
        ('termcolor', '2.0.0:'): 'termcolor_archive',
        ('wrapt', '2.0.0:'): 'wrapt',
    }
    dependency_mapping = dict((dep_name, tf_name)
                              for (dep_name, version_range), tf_name in available_system_libs.items()
                              if is_version_ok(version_range))
    python_mapping = dict((pkg_name, tf_name)
                          for (pkg_name, version_range), tf_name in python_system_libs.items()
                          if is_version_ok(version_range))

    if as_valid_libs:
        tf_names = [tf_name for tf_name, version_range in unused_system_libs.items()
                    if is_version_ok(version_range)]
        tf_names.extend(dependency_mapping.values())
        tf_names.extend(python_mapping.values())
        result = '\n'.join(['    "%s",' % name for name in sorted(tf_names)])
    else:
        result = dependency_mapping, python_mapping
    return result


class EB_TensorFlow(PythonPackage):
    """Support for building/installing TensorFlow."""

    @staticmethod
    def extra_options():
        # We only want to install mkl-dnn by default on x86_64 systems
        with_mkl_dnn_default = get_cpu_architecture() == X86_64
        extra_vars = {
            # see https://developer.nvidia.com/cuda-gpus
            'cuda_compute_capabilities': [[], "List of CUDA compute capabilities to build with", CUSTOM],
            'path_filter': [[], "List of patterns to be filtered out in paths in $CPATH and $LIBRARY_PATH", CUSTOM],
            'with_jemalloc': [None, "Make TensorFlow use jemalloc (usually enabled by default)", CUSTOM],
            'with_mkl_dnn': [with_mkl_dnn_default, "Make TensorFlow use Intel MKL-DNN", CUSTOM],
            'with_xla': [None, "Enable XLA JIT compiler for possible runtime optimization of models", CUSTOM],
            'test_script': [None, "Script to test TensorFlow installation with", CUSTOM],
        }

        return PythonPackage.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize TensorFlow easyblock."""
        super(EB_TensorFlow, self).__init__(*args, **kwargs)

        self.cfg['exts_defaultclass'] = 'PythonPackage'

        self.cfg['exts_default_options'] = {
            'download_dep_fail': True,
            'use_pip': True,
        }
        self.cfg['exts_filter'] = EXTS_FILTER_PYTHON_PACKAGES
        self.system_libs_info = None

        self.test_script = None

        # locate test script (if specified)
        if self.cfg['test_script']:
            # try to locate test script via obtain_file (just like sources & patches files)
            self.test_script = self.obtain_file(self.cfg['test_script'])
            if self.test_script and os.path.exists(self.test_script):
                self.log.info("Test script found: %s", self.test_script)
            else:
                raise EasyBuildError("Specified test script %s not found!", self.cfg['test_script'])

    def python_pkg_exists(self, name):
        """Check if the given python package exists/can be imported"""
        cmd = [self.python_cmd, '-c', 'import %s' % name]
        out, ec = run_cmd(cmd, log_ok=False)
        self.log.debug('Existence check for %s returned %s with output: %s', name, ec, out)
        return ec == 0

    def get_installed_python_packages(self):
        """Return list of Python package names that are installed

        Note that the names are reported by pip and might be different to the name that needs to be used to import it
        """
        # Check installed python packages but only check stdout, not stderr which might contain user facing warnings
        cmd_list = [self.python_cmd, '-m', 'pip', 'list', '--isolated', '--disable-pip-version-check',
                    '--format', 'json']
        full_cmd = ' '.join(cmd_list)
        self.log.info("Running command '%s'" % full_cmd)
        proc = subprocess_popen_text(cmd_list, env=os.environ)
        (stdout, stderr) = proc.communicate()
        ec = proc.returncode
        self.log.info("Command '%s' returned with %s: stdout: %s; stderr: %s" % (full_cmd, ec, stdout, stderr))
        if ec:
            raise EasyBuildError('Failed to determine installed python packages: %s', stderr)

        return [pkg['name'] for pkg in json.loads(stdout.strip())]

    def handle_jemalloc(self):
        """Figure out whether jemalloc support should be enabled or not."""
        if self.cfg['with_jemalloc'] is None:
            if LooseVersion(self.version) > LooseVersion('1.6'):
                # jemalloc bundled with recent versions of TensorFlow does not work on RHEL 6 or derivatives,
                # so disable it automatically if with_jemalloc was left unspecified
                os_name = get_os_name().replace(' ', '')
                rh_based_os = any(os_name.startswith(x) for x in ['centos', 'redhat', 'rhel', 'sl'])
                if rh_based_os and get_os_version().startswith('6.'):
                    self.log.info("Disabling jemalloc since bundled jemalloc does not work on RHEL 6 and derivatives")
                    self.cfg['with_jemalloc'] = False

            # if the above doesn't disable jemalloc support, then enable it by default
            if self.cfg['with_jemalloc'] is None:
                self.log.info("Enabling jemalloc support by default, since it was left unspecified")
                self.cfg['with_jemalloc'] = True

        else:
            # if with_jemalloc was specified, stick to that
            self.log.info("with_jemalloc was specified as %s, so sticking to it", self.cfg['with_jemalloc'])

    def write_wrapper(self, wrapper_dir, compiler, i_mpi_root):
        """Helper function to write a compiler wrapper."""
        wrapper_txt = INTEL_COMPILER_WRAPPER % {
            'compiler_path': which(compiler),
            'intel_mpi_root': i_mpi_root,
            'cpath': os.getenv('CPATH'),
            'intel_license_file': os.getenv('INTEL_LICENSE_FILE', os.getenv('LM_LICENSE_FILE')),
            'wrapper_dir': wrapper_dir,
        }
        wrapper = os.path.join(wrapper_dir, compiler)
        write_file(wrapper, wrapper_txt)
        if self.dry_run:
            self.dry_run_msg("Wrapper for '%s' was put in place: %s", compiler, wrapper)
        else:
            adjust_permissions(wrapper, stat.S_IXUSR)
            self.log.info("Using wrapper script for '%s': %s", compiler, which(compiler))

    def verify_system_libs_info(self):
        """Verifies that the stored info about $TF_SYSTEM_LIBS is complete"""
        available_libs_src = set(get_system_libs_from_tf(self.start_dir))
        available_libs_eb = set(split_tf_libs_txt(get_system_libs_for_version(self.version, as_valid_libs=True)))
        # If available_libs_eb is empty it is not an error e.g. it is not worth trying to make all old ECs work
        # So we just log it so it can be verified manually if required
        if not available_libs_eb:
            self.log.warning('TensorFlow EasyBlock does not have any information for $TF_SYSTEM_LIBS stored. ' +
                             'This means most dependencies will be downloaded at build time by TensorFlow.\n' +
                             'Available $TF_SYSTEM_LIBS according to the TensorFlow sources: %s',
                             sorted(available_libs_src))
            return
        # Those 2 sets should be equal. We determine the differences here to report better errors
        missing_libs = available_libs_src - available_libs_eb
        unknown_libs = available_libs_eb - available_libs_src
        if missing_libs or unknown_libs:
            if not available_libs_src:
                msg = 'Failed to determine available $TF_SYSTEM_LIBS from the source'
            else:
                msg = 'Values for $TF_SYSTEM_LIBS in the TensorFlow EasyBlock are incomplete.\n'
                if missing_libs:
                    # Libs available according to TF sources but not listed in this EasyBlock
                    msg += 'Missing entries for $TF_SYSTEM_LIBS: %s\n' % missing_libs
                if unknown_libs:
                    # Libs listed in this EasyBlock but not present in the TF sources -> Removed?
                    msg += 'Unrecognized entries for $TF_SYSTEM_LIBS: %s\n' % unknown_libs
                msg += 'The EasyBlock needs to be updated to fully work with TensorFlow version %s' % self.version
            if build_option('strict') == run.ERROR:
                raise EasyBuildError(msg)
            else:
                print_warning(msg)

    def get_system_libs(self):
        """
        Get list of dependencies for $TF_SYSTEM_LIBS

        Returns a tuple of lists: $TF_SYSTEM_LIBS names, include paths, library paths
        """
        dependency_mapping, python_mapping = get_system_libs_for_version(self.version)

        system_libs = []
        cpaths = []
        libpaths = []
        ignored_system_deps = []

        # Check direct dependencies
        dep_names = set(dep['name'] for dep in self.cfg.dependencies())
        for dep_name, tf_name in sorted(dependency_mapping.items(), key=lambda i: i[0].lower()):
            if dep_name in dep_names:
                system_libs.append(tf_name)
                # When using cURL (which uses the system OpenSSL), we also need to use "boringssl"
                # which essentially resolves to using OpenSSL as the API and library names are compatible
                if dep_name == 'cURL':
                    system_libs.append('boringssl')
                # For protobuf we need protobuf and protobuf-python where the latter depends on the former
                # For includes etc. we need to get the values from protobuf
                if dep_name == 'protobuf-python':
                    dep_name = 'protobuf'
                sw_root = get_software_root(dep_name)
                # Dependency might be filtered via --filter-deps. In that case assume globally installed version
                if not sw_root:
                    continue
                incpath = os.path.join(sw_root, 'include')
                if os.path.exists(incpath):
                    cpaths.append(incpath)
                    if dep_name == 'JsonCpp' and LooseVersion(self.version) < LooseVersion('2.3'):
                        # Need to add the install prefix or patch the sources:
                        # https://github.com/tensorflow/tensorflow/issues/42303
                        cpaths.append(sw_root)
                    if dep_name == 'protobuf':
                        # Need to set INCLUDEDIR as TF wants to symlink headers from there:
                        # https://github.com/tensorflow/tensorflow/issues/37835
                        env.setvar('INCLUDEDIR', incpath)
                libpath = get_software_libdir(dep_name)
                if libpath:
                    libpaths.append(os.path.join(sw_root, libpath))
            else:
                ignored_system_deps.append('%s (Dependency %s)' % (tf_name, dep_name))

        for pkg_name, tf_name in sorted(python_mapping.items(), key=lambda i: i[0].lower()):
            if self.python_pkg_exists(pkg_name):
                system_libs.append(tf_name)
            else:
                ignored_system_deps.append('%s (Python package %s)' % (tf_name, pkg_name))

        if ignored_system_deps:
            self.log.warning('For the following $TF_SYSTEM_LIBS dependencies TensorFlow will download a copy ' +
                             'because an EB dependency was not found: \n%s\n' +
                             'EC Dependencies: %s\n' +
                             'Installed Python packages: %s\n',
                             ', '.join(ignored_system_deps),
                             ', '.join(dep_names),
                             ', '.join(self.get_installed_python_packages()))
        else:
            self.log.info("All known TensorFlow $TF_SYSTEM_LIBS dependencies resolved via EasyBuild!")

        return system_libs, cpaths, libpaths

    def setup_build_dirs(self):
        """Setup temporary build directories"""
        # Tensorflow/Bazel needs a couple of directories where it stores build cache and artefacts
        tmpdir = tempfile.mkdtemp(suffix='-bazel-tf', dir=self.builddir)
        self.output_root_dir = os.path.join(tmpdir, 'output_root')
        self.output_base_dir = os.path.join(tmpdir, 'output_base')
        self.output_user_root_dir = os.path.join(tmpdir, 'output_user_root')
        self.wrapper_dir = os.path.join(tmpdir, 'wrapper_bin')
        # This (likely) needs to be a subdir of output_base
        self.install_base_dir = os.path.join(self.output_base_dir, 'inst_base')

    def configure_step(self):
        """Custom configuration procedure for TensorFlow."""

        binutils_root = get_software_root('binutils')
        if not binutils_root:
            raise EasyBuildError("Failed to determine installation prefix for binutils")
        self.binutils_bin_path = os.path.join(binutils_root, 'bin')

        # filter out paths from CPATH and LIBRARY_PATH. This is needed since bazel will pull some dependencies that
        # might conflict with dependencies on the system and/or installed with EB. For example: protobuf
        path_filter = self.cfg['path_filter']
        if path_filter:
            self.log.info("Filtering $CPATH and $LIBRARY_PATH with path filter %s", path_filter)
            for var in ['CPATH', 'LIBRARY_PATH']:
                path = os.getenv(var).split(os.pathsep)
                self.log.info("$%s old value was %s" % (var, path))
                filtered_path = os.pathsep.join([p for fil in path_filter for p in path if fil not in p])
                env.setvar(var, filtered_path)

        self.setup_build_dirs()

        use_wrapper = False
        if self.toolchain.comp_family() == toolchain.INTELCOMP:
            # put wrappers for Intel C/C++ compilers in place (required to make sure license server is found)
            # cfr. https://github.com/bazelbuild/bazel/issues/663
            for compiler in ('icc', 'icpc'):
                self.write_wrapper(self.wrapper_dir, compiler, 'NOT-USED-WITH-ICC')
            use_wrapper = True

        use_mpi = self.toolchain.options.get('usempi', False)
        mpi_home = ''
        if use_mpi:
            impi_root = get_software_root('impi')
            if impi_root:
                # put wrappers for Intel MPI compiler wrappers in place
                # (required to make sure license server and I_MPI_ROOT are found)
                for compiler in (os.getenv('MPICC'), os.getenv('MPICXX')):
                    self.write_wrapper(self.wrapper_dir, compiler, os.getenv('I_MPI_ROOT'))
                use_wrapper = True
                # set correct value for MPI_HOME
                mpi_home = os.path.join(impi_root, 'intel64')
            else:
                self.log.debug("MPI module name: %s", self.toolchain.MPI_MODULE_NAME[0])
                mpi_home = get_software_root(self.toolchain.MPI_MODULE_NAME[0])

            self.log.debug("Derived value for MPI_HOME: %s", mpi_home)

        if use_wrapper:
            env.setvar('PATH', os.pathsep.join([self.wrapper_dir, os.getenv('PATH')]))

        self.prepare_python()
        self.handle_jemalloc()

        self.verify_system_libs_info()
        self.system_libs_info = self.get_system_libs()

        cuda_root = get_software_root('CUDA')
        cudnn_root = get_software_root('cuDNN')
        opencl_root = get_software_root('OpenCL')
        tensorrt_root = get_software_root('TensorRT')
        nccl_root = get_software_root('NCCL')

        config_env_vars = {
            'CC_OPT_FLAGS': os.getenv('CXXFLAGS'),
            'MPI_HOME': mpi_home,
            'PYTHON_BIN_PATH': self.python_cmd,
            'PYTHON_LIB_PATH': os.path.join(self.installdir, self.pylibdir),
            'TF_CUDA_CLANG': '0',
            'TF_ENABLE_XLA': ('0', '1')[bool(self.cfg['with_xla'])],  # XLA JIT support
            'TF_NEED_CUDA': ('0', '1')[bool(cuda_root)],
            'TF_NEED_GCP': '0',  # Google Cloud Platform
            'TF_NEED_GDR': '0',
            'TF_NEED_HDFS': '0',  # Hadoop File System
            'TF_NEED_JEMALLOC': ('0', '1')[self.cfg['with_jemalloc']],
            'TF_NEED_MPI': ('0', '1')[bool(use_mpi)],
            'TF_NEED_OPENCL': ('0', '1')[bool(opencl_root)],
            'TF_NEED_OPENCL_SYCL': '0',
            'TF_NEED_ROCM': '0',
            'TF_NEED_S3': '0',  # Amazon S3 File System
            'TF_NEED_TENSORRT': '0',
            'TF_NEED_VERBS': '0',
            'TF_NEED_AWS': '0',  # Amazon AWS Platform
            'TF_NEED_KAFKA': '0',  # Amazon Kafka Platform
            'TF_SET_ANDROID_WORKSPACE': '0',
            'TF_DOWNLOAD_CLANG': '0',  # Still experimental in TF 2.1.0
            'TF_SYSTEM_LIBS': ','.join(self.system_libs_info[0]),
        }
        if cuda_root:
            cuda_version = get_software_version('CUDA')
            cuda_maj_min_ver = '.'.join(cuda_version.split('.')[:2])

            # $GCC_HOST_COMPILER_PATH should be set to path of the actual compiler (not the MPI compiler wrapper)
            if use_mpi:
                compiler_path = which(os.getenv('CC_SEQ'))
            else:
                compiler_path = which(os.getenv('CC'))

            # list of CUDA compute capabilities to use can be specifed in two ways (where (2) overrules (1)):
            # (1) in the easyconfig file, via the custom cuda_compute_capabilities;
            # (2) in the EasyBuild configuration, via --cuda-compute-capabilities configuration option;
            ec_cuda_cc = self.cfg['cuda_compute_capabilities']
            cfg_cuda_cc = build_option('cuda_compute_capabilities')
            cuda_cc = cfg_cuda_cc or ec_cuda_cc or []

            if cfg_cuda_cc and ec_cuda_cc:
                warning_msg = "cuda_compute_capabilities specified in easyconfig (%s) are overruled by " % ec_cuda_cc
                warning_msg += "--cuda-compute-capabilities configuration option (%s)" % cfg_cuda_cc
                print_warning(warning_msg)
            elif not cuda_cc:
                warning_msg = "No CUDA compute capabilities specified, so using TensorFlow default "
                warning_msg += "(which may not be optimal for your system).\nYou should use "
                warning_msg += "the --cuda-compute-capabilities configuration option or the cuda_compute_capabilities "
                warning_msg += "easyconfig parameter to specify a list of CUDA compute capabilities to compile with."
                print_warning(warning_msg)

            # TensorFlow 1.12.1 requires compute capability >= 3.5
            # see https://github.com/tensorflow/tensorflow/pull/25767
            if LooseVersion(self.version) >= LooseVersion('1.12.1'):
                faulty_comp_caps = [x for x in cuda_cc if LooseVersion(x) < LooseVersion('3.5')]
                if faulty_comp_caps:
                    error_msg = "TensorFlow >= 1.12.1 requires CUDA compute capabilities >= 3.5, "
                    error_msg += "found one or more older ones: %s"
                    raise EasyBuildError(error_msg, ', '.join(faulty_comp_caps))

            if cuda_cc:
                self.log.info("Compiling with specified list of CUDA compute capabilities: %s", ', '.join(cuda_cc))

            config_env_vars.update({
                'CUDA_TOOLKIT_PATH': cuda_root,
                'GCC_HOST_COMPILER_PATH': compiler_path,
                # This is the binutils bin folder: https://github.com/tensorflow/tensorflow/issues/39263
                'GCC_HOST_COMPILER_PREFIX': self.binutils_bin_path,
                'TF_CUDA_COMPUTE_CAPABILITIES': ','.join(cuda_cc),
                'TF_CUDA_VERSION': cuda_maj_min_ver,
            })

            # for recent TensorFlow versions, $TF_CUDA_PATHS and $TF_CUBLAS_VERSION must also be set
            if LooseVersion(self.version) >= LooseVersion('1.14'):

                # figure out correct major/minor version for CUBLAS from cublas_api.h
                cublas_api_header_glob_pattern = os.path.join(cuda_root, 'targets', '*', 'include', 'cublas_api.h')
                matches = glob.glob(cublas_api_header_glob_pattern)
                if len(matches) == 1:
                    cublas_api_header_path = matches[0]
                    cublas_api_header_txt = read_file(cublas_api_header_path)
                else:
                    raise EasyBuildError("Failed to isolate path to cublas_api.h: %s", matches)

                cublas_ver_parts = []
                for key in ['CUBLAS_VER_MAJOR', 'CUBLAS_VER_MINOR', 'CUBLAS_VER_PATCH']:
                    regex = re.compile("^#define %s ([0-9]+)" % key, re.M)
                    res = regex.search(cublas_api_header_txt)
                    if res:
                        cublas_ver_parts.append(res.group(1))
                    else:
                        raise EasyBuildError("Failed to find pattern '%s' in %s", regex.pattern, cublas_api_header_path)

                config_env_vars.update({
                    'TF_CUDA_PATHS': cuda_root,
                    'TF_CUBLAS_VERSION': '.'.join(cublas_ver_parts),
                })

            if cudnn_root:
                cudnn_version = get_software_version('cuDNN')
                cudnn_maj_min_patch_ver = '.'.join(cudnn_version.split('.')[:3])

                config_env_vars.update({
                    'CUDNN_INSTALL_PATH': cudnn_root,
                    'TF_CUDNN_VERSION': cudnn_maj_min_patch_ver,
                })
            else:
                raise EasyBuildError("TensorFlow has a strict dependency on cuDNN if CUDA is enabled")
            if nccl_root:
                nccl_version = get_software_version('NCCL')
                # Ignore the PKG_REVISION identifier if it exists (i.e., report 2.4.6 for 2.4.6-1 or 2.4.6-2)
                nccl_version = nccl_version.split('-')[0]
                config_env_vars.update({
                    'NCCL_INSTALL_PATH': nccl_root,
                })
            else:
                nccl_version = '1.3'  # Use simple downloadable version
            config_env_vars.update({
                'TF_NCCL_VERSION': nccl_version,
            })
            if tensorrt_root:
                tensorrt_version = get_software_version('TensorRT')
                config_env_vars.update({
                    'TF_NEED_TENSORRT': '1',
                    'TENSORRT_INSTALL_PATH': tensorrt_root,
                    'TF_TENSORRT_VERSION': tensorrt_version,
                })

        for (key, val) in sorted(config_env_vars.items()):
            env.setvar(key, val)

        # Does no longer apply (and might not be required at all) since 1.12.0
        if LooseVersion(self.version) < LooseVersion('1.12.0'):
            # patch configure.py (called by configure script) to avoid that Bazel abuses $HOME/.cache/bazel
            regex_subs = [(r"(run_shell\(\['bazel')",
                           r"\1, '--output_base=%s', '--install_base=%s'" % (self.output_base_dir,
                                                                             self.install_base_dir))]
            apply_regex_substitutions('configure.py', regex_subs)

        # Tell Bazel to not use $HOME/.cache/bazel at all
        # See https://docs.bazel.build/versions/master/output_directories.html
        env.setvar('TEST_TMPDIR', self.output_root_dir)
        cmd = self.cfg['preconfigopts'] + './configure ' + self.cfg['configopts']
        run_cmd(cmd, log_all=True, simple=True)

    def patch_crosstool_files(self):
        """Patches the CROSSTOOL files to include EasyBuild provided compiler paths"""
        inc_paths, lib_paths = [], []

        gcc_root = get_software_root('GCCcore') or get_software_root('GCC')
        if gcc_root:
            gcc_lib64 = os.path.join(gcc_root, 'lib64')
            lib_paths.append(gcc_lib64)

            gcc_ver = get_software_version('GCCcore') or get_software_version('GCC')

            # figure out location of GCC include files
            res = glob.glob(os.path.join(gcc_root, 'lib', 'gcc', '*', gcc_ver, 'include'))
            if res and len(res) == 1:
                gcc_lib_inc = res[0]
                inc_paths.append(gcc_lib_inc)
            else:
                raise EasyBuildError("Failed to pinpoint location of GCC include files: %s", res)

            # make sure include-fixed directory is where we expect it to be
            gcc_lib_inc_fixed = os.path.join(os.path.dirname(gcc_lib_inc), 'include-fixed')
            if os.path.exists(gcc_lib_inc_fixed):
                inc_paths.append(gcc_lib_inc_fixed)
            else:
                self.log.info("Derived directory %s does not exist, so discarding it", gcc_lib_inc_fixed)

            # also check on location of include/c++/<gcc version> directory
            gcc_cplusplus_inc = os.path.join(gcc_root, 'include', 'c++', gcc_ver)
            if os.path.exists(gcc_cplusplus_inc):
                inc_paths.append(gcc_cplusplus_inc)
            else:
                raise EasyBuildError("Derived directory %s does not exist", gcc_cplusplus_inc)
        else:
            raise EasyBuildError("Failed to determine installation prefix for GCC")

        cuda_root = get_software_root('CUDA')
        if cuda_root:
            inc_paths.append(os.path.join(cuda_root, 'include'))
            lib_paths.append(os.path.join(cuda_root, 'lib64'))

        # fix hardcoded locations of compilers & tools
        cxx_inc_dirs = ['cxx_builtin_include_directory: "%s"' % resolve_path(p) for p in inc_paths]
        cxx_inc_dirs += ['cxx_builtin_include_directory: "%s"' % p for p in inc_paths]
        regex_subs = [
            (r'-B/usr/bin/', '-B%s %s' % (self.binutils_bin_path, ' '.join('-L%s/' % p for p in lib_paths))),
            (r'(cxx_builtin_include_directory:).*', ''),
            (r'^toolchain {', 'toolchain {\n' + '\n'.join(cxx_inc_dirs)),
        ]
        for tool in ['ar', 'cpp', 'dwp', 'gcc', 'gcov', 'ld', 'nm', 'objcopy', 'objdump', 'strip']:
            path = which(tool)
            if path:
                regex_subs.append((os.path.join('/usr', 'bin', tool), path))
            else:
                raise EasyBuildError("Failed to determine path to '%s'", tool)

        # -fPIE/-pie and -fPIC are not compatible, so patch out hardcoded occurences of -fPIE/-pie if -fPIC is used
        if self.toolchain.options.get('pic', None):
            regex_subs.extend([('-fPIE', '-fPIC'), ('"-pie"', '"-fPIC"')])

        # patch all CROSSTOOL* scripts to fix hardcoding of locations of binutils/GCC binaries
        for path, dirnames, filenames in os.walk(os.getcwd()):
            for filename in filenames:
                if filename.startswith('CROSSTOOL'):
                    full_path = os.path.join(path, filename)
                    self.log.info("Patching %s", full_path)
                    apply_regex_substitutions(full_path, regex_subs)

    def build_step(self):
        """Custom build procedure for TensorFlow."""

        # pre-create target installation directory
        mkdir(os.path.join(self.installdir, self.pylibdir), parents=True)

        # This seems to be no longer required since at least 2.0, likely also for older versions
        if LooseVersion(self.version) < LooseVersion('2.0'):
            self.patch_crosstool_files()

        # compose "bazel build" command with all its options...
        cmd = [
            self.cfg['prebuildopts'],
            'bazel',
            '--output_base=%s' % self.output_base_dir,
            '--install_base=%s' % self.install_base_dir,
            '--output_user_root=%s' % self.output_user_root_dir,
            'build',
        ]

        # build with optimization enabled
        # cfr. https://docs.bazel.build/versions/master/user-manual.html#flag--compilation_mode
        cmd.append('--compilation_mode=opt')

        # select 'opt' config section (this is *not* the same as --compilation_mode=opt!)
        # https://docs.bazel.build/versions/master/user-manual.html#flag--config
        cmd.append('--config=opt')

        # make Bazel print full command line + make it verbose on failures
        # https://docs.bazel.build/versions/master/user-manual.html#flag--subcommands
        # https://docs.bazel.build/versions/master/user-manual.html#flag--verbose_failures
        cmd.extend(['--subcommands', '--verbose_failures'])

        # Disable support of AWS platform via config switch introduced in 1.12.1
        if LooseVersion(self.version) >= LooseVersion('1.12.1'):
            cmd.append('--config=noaws')

        # Bazel seems to not be able to handle a large amount of parallel jobs, e.g. 176 on some Power machines,
        # and will hang forever building the TensorFlow package.
        # So limit to something high but still reasonable while allowing ECs to overwrite it
        parallel = self.cfg['parallel']
        if self.cfg['maxparallel'] is None:
            parallel = min(parallel, 64)
        cmd.append('--jobs=%s' % parallel)

        if self.toolchain.options.get('pic', None):
            cmd.append('--copt="-fPIC"')

        # include install location of Python packages in $PYTHONPATH,
        # and specify that value of $PYTHONPATH should be passed down into Bazel build environment;
        # this is required to make sure that Python packages included as extensions are found at build time;
        # see also https://github.com/tensorflow/tensorflow/issues/22395
        pythonpath = os.getenv('PYTHONPATH', '')
        env.setvar('PYTHONPATH', os.pathsep.join([os.path.join(self.installdir, self.pylibdir), pythonpath]))

        # Make TF find our modules. LD_LIBRARY_PATH gets automatically added by configure.py
        cpaths, libpaths = self.system_libs_info[1:]
        if cpaths:
            cmd.append("--action_env=CPATH='%s'" % ':'.join(cpaths))
        if libpaths:
            cmd.append("--action_env=LIBRARY_PATH='%s'" % ':'.join(libpaths))
        cmd.append('--action_env=PYTHONPATH')
        # Also export $EBPYTHONPREFIXES to handle the multi-deps python setup
        # See https://github.com/easybuilders/easybuild-easyblocks/pull/1664
        if 'EBPYTHONPREFIXES' in os.environ:
            cmd.append('--action_env=EBPYTHONPREFIXES')

        # Ignore user environment for Python
        cmd.append('--action_env=PYTHONNOUSERSITE=1')

        # use same configuration for both host and target programs, which can speed up the build
        # only done when optarch is enabled, since this implicitely assumes that host and target platform are the same
        # see https://docs.bazel.build/versions/master/guide.html#configurations
        if self.toolchain.options.get('optarch'):
            cmd.append('--distinct_host_configuration=false')

        cmd.append(self.cfg['buildopts'])

        # TF 2 (final) sets this in configure
        if LooseVersion(self.version) < LooseVersion('2.0'):
            if get_software_root('CUDA'):
                cmd.append('--config=cuda')

        # if mkl-dnn is listed as a dependency it is used. Otherwise downloaded if with_mkl_dnn is true
        mkl_root = get_software_root('mkl-dnn')
        if mkl_root:
            cmd.extend(['--config=mkl'])
            cmd.insert(0, "export TF_MKL_DOWNLOAD=0 &&")
            cmd.insert(0, "export TF_MKL_ROOT=%s &&" % mkl_root)
        elif self.cfg['with_mkl_dnn']:
            # this makes TensorFlow use mkl-dnn (cfr. https://github.com/01org/mkl-dnn)
            cmd.extend(['--config=mkl'])
            cmd.insert(0, "export TF_MKL_DOWNLOAD=1 && ")

        # specify target of the build command as last argument
        cmd.append('//tensorflow/tools/pip_package:build_pip_package')

        run_cmd(' '.join(cmd), log_all=True, simple=True, log_ok=True)

        # run generated 'build_pip_package' script to build the .whl
        cmd = "bazel-bin/tensorflow/tools/pip_package/build_pip_package %s" % self.builddir
        run_cmd(cmd, log_all=True, simple=True, log_ok=True)

    def test_step(self):
        """No (reliable) custom test procedure for TensorFlow."""
        pass

    def install_step(self):
        """Custom install procedure for TensorFlow."""
        # find .whl file that was built, and install it using 'pip install'
        if ("-rc" in self.version):
            whl_version = self.version.replace("-rc", "rc")
        else:
            whl_version = self.version

        whl_paths = glob.glob(os.path.join(self.builddir, 'tensorflow-%s-*.whl' % whl_version))
        if not whl_paths:
            whl_paths = glob.glob(os.path.join(self.builddir, 'tensorflow-*.whl'))
        if len(whl_paths) == 1:
            # --ignore-installed is required to ensure *this* wheel is installed
            cmd = "pip install --ignore-installed --prefix=%s %s" % (self.installdir, whl_paths[0])

            # if extensions are listed, assume they will provide all required dependencies,
            # so use --no-deps to prevent pip from downloading & installing them
            if self.cfg['exts_list']:
                cmd += ' --no-deps'

            run_cmd(cmd, log_all=True, simple=True, log_ok=True)
        else:
            raise EasyBuildError("Failed to isolate built .whl in %s: %s", whl_paths, self.builddir)

        # Fix for https://github.com/tensorflow/tensorflow/issues/6341 on Python < 3.3
        # If the site-packages/google/__init__.py file is missing, make it an empty file.
        # This fixes the "No module named google.protobuf" error that sometimes shows up during sanity_check
        # For Python >= 3.3 the logic is reversed: The __init__.py must not exist.
        # See e.g. http://python-notes.curiousefficiency.org/en/latest/python_concepts/import_traps.html
        google_protobuf_dir = os.path.join(self.installdir, self.pylibdir, 'google', 'protobuf')
        google_init_file = os.path.join(self.installdir, self.pylibdir, 'google', '__init__.py')
        if LooseVersion(det_python_version(self.python_cmd)) < LooseVersion('3.3'):
            if os.path.isdir(google_protobuf_dir) and not is_readable(google_init_file):
                self.log.debug("Creating (empty) missing %s", google_init_file)
                write_file(google_init_file, '')
        else:
            if os.path.exists(google_init_file):
                self.log.debug("Removing %s for Python >= 3.3", google_init_file)
                remove_file(google_init_file)

        # Fix cuda header paths
        # This is needed for building custom TensorFlow ops
        if LooseVersion(self.version) < LooseVersion('1.14'):
            pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
            regex_subs = [(r'#include "cuda/include/', r'#include "')]
            base_path = os.path.join(self.installdir, 'lib', 'python%s' % pyshortver, 'site-packages', 'tensorflow',
                                     'include', 'tensorflow')
            for header in glob.glob(os.path.join(base_path, 'stream_executor', 'cuda', 'cuda*.h')) + glob.glob(
                    os.path.join(base_path, 'core', 'util', 'cuda*.h')):
                apply_regex_substitutions(header, regex_subs)

    def sanity_check_step(self):
        """Custom sanity check for TensorFlow."""
        custom_paths = {
            'files': ['bin/tensorboard'],
            'dirs': [self.pylibdir],
        }

        custom_commands = [
            "%s -c 'import tensorflow'" % self.python_cmd,
            # tf_should_use importsweakref.finalize, which requires backports.weakref for Python < 3.4
            "%s -c 'from tensorflow.python.util import tf_should_use'" % self.python_cmd,
        ]
        res = super(EB_TensorFlow, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

        # test installation using MNIST tutorial examples
        if self.cfg['runtest']:
            pythonpath = os.getenv('PYTHONPATH', '')
            env.setvar('PYTHONPATH', os.pathsep.join([os.path.join(self.installdir, self.pylibdir), pythonpath]))

            mnist_pys = []

            if LooseVersion(self.version) < LooseVersion('2.0'):
                mnist_pys.append('mnist_with_summaries.py')

            if LooseVersion(self.version) < LooseVersion('1.13'):
                # mnist_softmax.py was removed in TensorFlow 1.13.x
                mnist_pys.append('mnist_softmax.py')

            for mnist_py in mnist_pys:
                datadir = tempfile.mkdtemp(suffix='-tf-%s-data' % os.path.splitext(mnist_py)[0])
                logdir = tempfile.mkdtemp(suffix='-tf-%s-logs' % os.path.splitext(mnist_py)[0])
                mnist_py = os.path.join(self.start_dir, 'tensorflow', 'examples', 'tutorials', 'mnist', mnist_py)
                cmd = "%s %s --data_dir %s --log_dir %s" % (self.python_cmd, mnist_py, datadir, logdir)
                run_cmd(cmd, log_all=True, simple=True, log_ok=True)

            # run test script (if any)
            if self.test_script:
                # copy test script to build dir before running it, to avoid that a file named 'tensorflow.py'
                # (a customized TensorFlow easyblock for example) breaks 'import tensorflow'
                test_script = os.path.join(self.builddir, os.path.basename(self.test_script))
                copy_file(self.test_script, test_script)

                run_cmd("python %s" % test_script, log_all=True, simple=True, log_ok=True)

        return res
