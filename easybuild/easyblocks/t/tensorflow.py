##
# Copyright 2017-2025 Ghent University
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
@author: Alexander Grund (TU Dresden)
"""
import glob
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from itertools import chain

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.pythonpackage import PythonPackage, det_python_version
from easybuild.easyblocks.python import EXTS_FILTER_PYTHON_PACKAGES
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option, IGNORE, WARN, ERROR
from easybuild.tools.filetools import adjust_permissions, apply_regex_substitutions, copy_file, mkdir, resolve_path
from easybuild.tools.filetools import is_readable, read_file, symlink, which, write_file, remove_file
from easybuild.tools.modules import get_software_root, get_software_version, get_software_libdir
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import AARCH64, X86_64, get_cpu_architecture, get_os_name, get_os_version
from easybuild.tools.toolchain.toolchain import RPATH_WRAPPERS_SUBDIR


CPU_DEVICE = 'cpu'
GPU_DEVICE = 'gpu'

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

KNOWN_BINUTILS = ('ar', 'as', 'dwp', 'ld', 'ld.bfd', 'ld.gold', 'nm', 'objcopy', 'objdump', 'strip')


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
        ('Abseil', '2.9.0:'): 'com_google_absl',
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
        ('LMDB', '2.0.0:2.13.0'): 'lmdb',
        ('NASM', '2.0.0:'): 'nasm',
        ('nsync', '2.0.0:'): 'nsync',
        ('PCRE', '2.0.0:2.6.0'): 'pcre',
        ('protobuf', '2.0.0:'): 'com_google_protobuf',
        ('pybind11', '2.2.0:'): 'pybind11',
        ('snappy', '2.0.0:'): 'snappy',
        ('SQLite', '2.0.0:'): 'org_sqlite',
        ('SWIG', '2.0.0:2.4.0'): 'swig',
        ('zlib', '2.0.0:2.2.0'): 'zlib_archive',
        ('zlib', '2.2.0:'): 'zlib',
    }
    # Software recognized by TF but which is always disabled (usually because no EC is known)
    # Format: <TF name>: <version range>
    unused_system_libs = {
        'boringssl': '2.0.0:',  # Implied by cURL and existence of OpenSSL anywhere in the dependency chain
        'com_github_googleapis_googleapis': '2.0.0:2.5.0',
        'com_github_googlecloudplatform_google_cloud_cpp': '2.0.0:',  # Not used due to $TF_NEED_GCP=0
        'com_github_grpc_grpc': '2.2.0:',
        'com_googlesource_code_re2': '2.0.0:',  # Requires the RE2 version with Abseil (or 2023-06-01+)
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
        ('dill', '2.4.0:'): 'dill_archive',
        ('enum', '2.0.0:2.8.0'): 'enum34_archive',  # Part of Python3
        ('flatbuffers', '2.4.0:'): 'flatbuffers',
        ('functools', '2.0.0:'): 'functools32_archive',  # Part of Python3
        ('gast', '2.0.0:'): 'gast_archive',
        ('google.protobuf', '2.0.0:'): 'com_google_protobuf',
        ('keras_applications', '2.0.0:2.2.0'): 'keras_applications_archive',
        ('opt_einsum', '2.0.0:2.15.0'): 'opt_einsum_archive',
        ('pasta', '2.0.0:'): 'pasta',
        ('six', '2.0.0:'): 'six_archive',  # Part of Python EC
        ('tblib', '2.4.0:'): 'tblib_archive',
        ('termcolor', '2.0.0:'): 'termcolor_archive',
        ('typing_extensions', '2.4.0:'): 'typing_extensions_archive',
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


def get_bazel_version():
    """Get the Bazel version as a LooseVersion. Error if not found"""
    version = get_software_version('Bazel')
    if version is None:
        raise EasyBuildError('Failed to determine Bazel version - is it listed as a (build) dependency?')
    return LooseVersion(version)


class EB_TensorFlow(PythonPackage):
    """Support for building/installing TensorFlow."""

    @staticmethod
    def extra_options():
        extra_vars = {
            'path_filter': [[], "List of patterns to be filtered out in paths in $CPATH and $LIBRARY_PATH", CUSTOM],
            'with_jemalloc': [None, "Make TensorFlow use jemalloc (usually enabled by default). " +
                                    "Unsupported starting at TensorFlow 1.12!", CUSTOM],
            'with_mkl_dnn': [None, "Make TensorFlow use Intel MKL-DNN / oneDNN and configure with --config=mkl "
                                   "(enabled by default where supported for TensorFlow versions before 2.4.0)",
                             CUSTOM],
            'with_xla': [None, "Enable XLA JIT compiler for possible runtime optimization of models", CUSTOM],
            'test_script': [None, "Script to test TensorFlow installation with", CUSTOM],
            'test_targets': [[], "List of Bazel targets which should be run during the test step", CUSTOM],
            'test_tag_filters_cpu': ['', "Comma-separated list of tags to filter for during the CPU test step", CUSTOM],
            'test_tag_filters_gpu': ['', "Comma-separated list of tags to filter for during the GPU test step", CUSTOM],
            'testopts_gpu': ['', 'Test options for the GPU test step', CUSTOM],
            'test_max_parallel': [None, "Maximum number of test jobs to run in parallel (GPU tests are limited by " +
                                  "the number of GPUs). Use None (default) to automatically determine a value", CUSTOM],
            'jvm_max_memory': [4096, "Maximum amount of memory in MB used for the JVM running Bazel." +
                               "Use None to not set a specific limit (uses a default value).", CUSTOM],
        }

        return PythonPackage.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize TensorFlow easyblock."""
        super(EB_TensorFlow, self).__init__(*args, **kwargs)

        with self.cfg.disable_templating():
            self.cfg['exts_defaultclass'] = 'PythonPackage'

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
        cmd = self.python_cmd + " -c 'import %s'" % name
        res = run_shell_cmd(cmd, fail_on_error=False)
        self.log.debug('Existence check for %s returned %s with output: %s', name, res.exit_code, res.output)
        return res.exit_code == 0

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
            'compiler_path': which(compiler, on_error=IGNORE if self.dry_run else ERROR),
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
                    msg += 'Missing entries for $TF_SYSTEM_LIBS: %s\n' % sorted(missing_libs)
                if unknown_libs:
                    # Libs listed in this EasyBlock but not present in the TF sources -> Removed?
                    msg += 'Unrecognized entries for $TF_SYSTEM_LIBS: %s\n' % sorted(unknown_libs)
                msg += 'The EasyBlock needs to be updated to fully work with TensorFlow version %s' % self.version
            if build_option('strict') == ERROR:
                raise EasyBuildError(msg)
            else:
                print_warning(msg)

    def get_system_libs(self):
        """
        Get list of dependencies for $TF_SYSTEM_LIBS

        Returns a tuple of lists: $TF_SYSTEM_LIBS names, include paths, library paths
        """
        dependency_mapping, python_mapping = get_system_libs_for_version(self.version)
        # Some TF dependencies require both a (usually C++) dependency and a Python package
        deps_with_python_pkg = set(tf_name for tf_name in dependency_mapping.values()
                                   if tf_name in python_mapping.values())

        system_libs = []
        cpaths = []
        libpaths = []
        ignored_system_deps = []

        # Check direct dependencies
        dep_names = set(dep['name'] for dep in self.cfg.dependencies())
        for dep_name, tf_name in sorted(dependency_mapping.items(), key=lambda i: i[0].lower()):
            if dep_name in dep_names:
                if tf_name in deps_with_python_pkg:
                    pkg_name = next(cur_pkg_name for cur_pkg_name, cur_tf_name in python_mapping.items()
                                    if cur_tf_name == tf_name)
                    # Simply ignore. Error reporting is done in the other loop
                    if not self.python_pkg_exists(pkg_name):
                        continue
                system_libs.append(tf_name)
                # When using cURL (which uses the system OpenSSL), we also need to use "boringssl"
                # which essentially resolves to using OpenSSL as the API and library names are compatible
                if dep_name == 'cURL':
                    system_libs.append('boringssl')
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
                        if LooseVersion(self.version) < LooseVersion('2.4'):
                            # Need to set INCLUDEDIR as TF wants to symlink files from there:
                            # https://github.com/tensorflow/tensorflow/issues/37835
                            env.setvar('INCLUDEDIR', incpath)
                        else:
                            env.setvar('PROTOBUF_INCLUDE_PATH', incpath)
                libpath = get_software_libdir(dep_name)
                if libpath:
                    libpaths.append(os.path.join(sw_root, libpath))
            else:
                ignored_system_deps.append('%s (Dependency %s)' % (tf_name, dep_name))

        for pkg_name, tf_name in sorted(python_mapping.items(), key=lambda i: i[0].lower()):
            if self.python_pkg_exists(pkg_name):
                # If it is in deps_with_python_pkg we already added it
                if tf_name not in deps_with_python_pkg:
                    system_libs.append(tf_name)
            else:
                ignored_system_deps.append('%s (Python package %s)' % (tf_name, pkg_name))

        # If we use OpenSSL (potentially as a wrapper) somewhere in the chain we must tell TF to use it too
        openssl_root = get_software_root('OpenSSL')
        if openssl_root:
            if 'boringssl' not in system_libs:
                system_libs.append('boringssl')
            incpath = os.path.join(openssl_root, 'include')
            if os.path.exists(incpath):
                cpaths.append(incpath)
            libpath = get_software_libdir('OpenSSL')
            if libpath:
                libpaths.append(os.path.join(openssl_root, libpath))

        if ignored_system_deps:
            print_warning('%d TensorFlow dependencies have not been resolved by EasyBuild. Check the log for details.',
                          len(ignored_system_deps))
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
        # This is either the builddir (for standalone builds) or the extension sub folder when TF is an extension
        # Either way this folder only contains the folder with the sources and hence we can use fixed names
        # for the subfolders
        parent_dir = os.path.dirname(self.start_dir)
        # Path where Bazel will store its output, build artefacts etc.
        self.output_user_root_dir = os.path.join(parent_dir, 'bazel-root')
        # Folder where wrapper binaries can be placed, where required. TODO: Replace by --action_env cmds
        self.wrapper_dir = os.path.join(parent_dir, 'wrapper_bin')
        mkdir(self.wrapper_dir)

    @contextmanager
    def set_tmp_dir(self):
        # TF uses the temporary folder, which becomes quite large (~2 GB) so use the build folder explicitely.
        old_tmpdir = os.environ['TMPDIR']
        tmpdir = os.path.join(self.builddir, 'tmpdir')
        mkdir(tmpdir)
        os.environ['TMPDIR'] = tmpdir
        try:
            yield tmpdir
        finally:
            os.environ['TMPDIR'] = old_tmpdir

    def configure_step(self):
        """Custom configuration procedure for TensorFlow."""

        self.setup_build_dirs()

        # Bazel seems to not be able to handle a large amount of parallel jobs, e.g. 176 on some Power machines,
        # and will hang forever building the TensorFlow package.
        # So limit to something high but still reasonable while allowing ECs to overwrite it
        if self.cfg['maxparallel'] is None:
            # Seemingly Bazel around 3.x got better, so double the max there
            bazel_max = 64 if get_bazel_version() < '3.0.0' else 128
            self.cfg.parallel = min(self.cfg.parallel, bazel_max)

        # determine location where binutils' ld command is installed
        # note that this may be an RPATH wrapper script (when EasyBuild is configured with --rpath)
        ld_path = which('ld', on_error=ERROR)
        self.binutils_bin_path = os.path.dirname(ld_path)
        if self.toolchain.is_rpath_wrapper(ld_path):
            # TF expects all binutils binaries in a single path but newer EB puts each in its own subfolder
            # This new layout is: <prefix>/RPATH_WRAPPERS_SUBDIR/<util>_folder/<util>
            rpath_wrapper_root = os.path.dirname(os.path.dirname(ld_path))
            if os.path.basename(rpath_wrapper_root) == RPATH_WRAPPERS_SUBDIR:
                # Add symlinks to each binutils binary into a single folder
                new_rpath_wrapper_dir = os.path.join(self.wrapper_dir, RPATH_WRAPPERS_SUBDIR)
                binutils_root = get_software_root('binutils')
                if binutils_root:
                    self.log.debug("Using binutils dependency at %s to gather binutils files.", binutils_root)
                    binutils_files = next(os.walk(os.path.join(binutils_root, 'bin')))[2]
                else:
                    # binutils might be filtered (--filter-deps), so recursively gather files in the rpath wrapper dir
                    binutils_files = {f for (_, _, files) in os.walk(rpath_wrapper_root) for f in files}
                    # And add known ones
                    binutils_files.update(KNOWN_BINUTILS)
                self.log.info("Found %s to be an rpath wrapper. Adding symlinks for binutils (%s) to %s.",
                              ld_path, ', '.join(binutils_files), new_rpath_wrapper_dir)
                mkdir(new_rpath_wrapper_dir)
                for file in binutils_files:
                    # use `which` to take rpath wrappers where available
                    # Ignore missing ones if binutils was filtered (in which case we used a heuristic)
                    path = which(file, on_error=ERROR if binutils_root else WARN)
                    if path:
                        symlink(path, os.path.join(new_rpath_wrapper_dir, file))
                self.binutils_bin_path = new_rpath_wrapper_dir

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

        self.verify_system_libs_info()
        self.system_libs_info = self.get_system_libs()

        # Options passed to the target (build/test), e.g. --config arguments
        self.target_opts = []

        cuda_root = get_software_root('CUDA')
        cudnn_root = get_software_root('cuDNN')
        opencl_root = get_software_root('OpenCL')
        tensorrt_root = get_software_root('TensorRT')
        nccl_root = get_software_root('NCCL')

        self._with_cuda = bool(cuda_root)

        config_env_vars = {
            'CC_OPT_FLAGS': os.getenv('CXXFLAGS'),
            'MPI_HOME': mpi_home,
            'PYTHON_BIN_PATH': self.python_cmd,
            'PYTHON_LIB_PATH': os.path.join(self.installdir, self.pylibdir),
            'TF_CUDA_CLANG': '0',
            'TF_DOWNLOAD_CLANG': '0',  # Still experimental in TF 2.1.0
            'TF_ENABLE_XLA': ('0', '1')[bool(self.cfg['with_xla'])],  # XLA JIT support
            'TF_NEED_CUDA': ('0', '1')[self._with_cuda],
            'TF_NEED_OPENCL': ('0', '1')[bool(opencl_root)],
            'TF_NEED_ROCM': '0',
            'TF_NEED_TENSORRT': '0',
            'TF_SET_ANDROID_WORKSPACE': '0',
            'TF_SYSTEM_LIBS': ','.join(self.system_libs_info[0]),
        }
        if LooseVersion(self.version) < LooseVersion('1.10'):
            config_env_vars['TF_NEED_S3'] = '0'  # Renamed to TF_NEED_AWS in 1.9.0-rc2 and 1.10, not 1.9.0
        # Options removed in 1.12.0
        if LooseVersion(self.version) < LooseVersion('1.12'):
            self.handle_jemalloc()
            config_env_vars.update({
                'TF_NEED_AWS': '0',  # Amazon AWS Platform
                'TF_NEED_GCP': '0',  # Google Cloud Platform
                'TF_NEED_GDR': '0',
                'TF_NEED_HDFS': '0',  # Hadoop File System
                'TF_NEED_JEMALLOC': ('0', '1')[self.cfg['with_jemalloc']],
                'TF_NEED_KAFKA': '0',  # Amazon Kafka Platform
                'TF_NEED_VERBS': '0',
            })
        elif self.cfg['with_jemalloc'] is True:
            print_warning('Jemalloc is not supported in TensorFlow %s, the EC option with_jemalloc has no effect',
                          self.version)
        # Disable support of some features via config switch introduced in 1.12.1
        if LooseVersion(self.version) >= LooseVersion('1.12.1'):
            self.target_opts += ['--config=noaws', '--config=nogcp', '--config=nohdfs']
            # Removed in 2.1
            if LooseVersion(self.version) < LooseVersion('2.1'):
                self.target_opts.append('--config=nokafka')
        # MPI support removed in 2.1
        if LooseVersion(self.version) < LooseVersion('2.1'):
            config_env_vars['TF_NEED_MPI'] = ('0', '1')[bool(use_mpi)]
        # SYCL support removed in 2.4
        if LooseVersion(self.version) < LooseVersion('2.4'):
            config_env_vars['TF_NEED_OPENCL_SYCL'] = '0'
        # Clang toggle since 2.14.0
        if LooseVersion(self.version) > LooseVersion('2.13'):
            config_env_vars['TF_NEED_CLANG'] = '0'
        # Hermietic python version since 2.14.0
        if LooseVersion(self.version) > LooseVersion('2.13'):
            pyver = det_python_version(self.python_cmd)
            config_env_vars['TF_PYTHON_VERSION'] = '.'.join(pyver.split('.')[:2])

        if self._with_cuda:
            cuda_version = get_software_version('CUDA')
            cuda_maj_min_ver = '.'.join(cuda_version.split('.')[:2])

            # $GCC_HOST_COMPILER_PATH should be set to path of the actual compiler (not the MPI compiler wrapper)
            if use_mpi:
                compiler_path = which(os.getenv('CC_SEQ'), on_error=ERROR)
            else:
                compiler_path = which(os.getenv('CC'), on_error=ERROR)

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

        configure_py_contents = read_file('configure.py')
        for key, val in sorted(config_env_vars.items()):
            if key.startswith('TF_') and key not in configure_py_contents:
                self.log.warning('Did not find %s option in configure.py. Setting might not have any effect', key)
            env.setvar(key, val)

        # configure.py (called by configure script) already calls bazel to determine the bazel version
        # Since 2.3.0 `bazel --version` is used which doesn't extract bazel, prior it did
        # Hence make sure it doesn't extract into $HOME/.cache/bazel
        if LooseVersion(self.version) < LooseVersion('2.3.0'):
            regex_subs = [(r"('bazel', '--batch')",
                           r"\1, '--output_user_root=%s'" % self.output_user_root_dir)]
            apply_regex_substitutions('configure.py', regex_subs)

        cmd = self.cfg['preconfigopts'] + './configure ' + self.cfg['configopts']
        run_shell_cmd(cmd)

        # when building on Arm 64-bit we can't just use --copt=-mcpu=native (or likewise for any -mcpu=...),
        # because it breaks the build of XNNPACK;
        # see also https://github.com/easybuilders/easybuild-easyconfigs/issues/18899
        if get_cpu_architecture() == AARCH64:
            tf_conf_bazelrc = os.path.join(self.start_dir, '.tf_configure.bazelrc')
            regex_subs = [
                # use --per_file_copt instead of --copt to selectively use -mcpu=native (not for XNNPACK),
                # the leading '-' ensures that -mcpu=native is *not* used when building XNNPACK;
                # see https://github.com/google/XNNPACK/issues/5566 + https://bazel.build/docs/user-manual#per-file-copt
                ('--copt=-mcpu=', '--per_file_copt=-.*XNNPACK/.*@-mcpu='),
            ]
            apply_regex_substitutions(tf_conf_bazelrc, regex_subs)

    def patch_crosstool_files(self):
        """Patches the CROSSTOOL files to include EasyBuild provided compiler paths"""
        inc_paths, lib_paths = [], []

        gcc_root = get_software_root('GCCcore') or get_software_root('GCC')
        if gcc_root:
            gcc_lib64 = os.path.join(gcc_root, 'lib64')
            lib_paths.append(gcc_lib64)

            gcc_ver = get_software_version('GCCcore') or get_software_version('GCC')

            # figure out location of GCC include files
            # make sure we don't pick up the nvptx-none directory by looking for a specific include file
            res = glob.glob(os.path.join(gcc_root, 'lib', 'gcc', '*', gcc_ver, 'include', 'immintrin.h'))
            if res and len(res) == 1:
                gcc_lib_inc = os.path.dirname(res[0])
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
        required_tools = {'ar', 'cpp', 'dwp', 'gcc', 'gcov', 'ld', 'nm', 'objcopy', 'objdump', 'strip'}
        for tool in set(chain(required_tools, KNOWN_BINUTILS)):
            path = which(tool, on_error=ERROR if tool in required_tools else WARN)
            if path:
                regex_subs.append((os.path.join('/usr', 'bin', tool), path))

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

        bazel_version = get_bazel_version()

        # pre-create target installation directory
        mkdir(os.path.join(self.installdir, self.pylibdir), parents=True)

        # This seems to be no longer required since at least 2.0, likely also for older versions
        if LooseVersion(self.version) < LooseVersion('2.0'):
            self.patch_crosstool_files()

        # Options passed to the bazel command
        self.bazel_opts = [
            '--output_user_root=%s' % self.output_user_root_dir,
        ]
        # Increase time to wait for bazel to start, available since 4.0+
        if bazel_version >= '4.0.0':
            self.bazel_opts.append('--local_startup_timeout_secs=300')  # 5min

        # Environment variables and values needed for Bazel actions.
        action_env = {}
        # A value of None is interpreted as using the invoking environments value
        INHERIT = None  # For better readability

        jvm_max_memory = self.cfg['jvm_max_memory']
        if jvm_max_memory:
            jvm_startup_memory = min(512, int(jvm_max_memory))
            self.bazel_opts.extend([
                '--host_jvm_args=-Xms%sm' % jvm_startup_memory,
                '--host_jvm_args=-Xmx%sm' % jvm_max_memory
            ])

        if self.toolchain.options.get('debug', None):
            self.target_opts.append('--strip=never')
            self.target_opts.append('--compilation_mode=dbg')
            self.target_opts.append('--copt="-Og"')
        else:
            # build with optimization enabled
            # cfr. https://docs.bazel.build/versions/master/user-manual.html#flag--compilation_mode
            self.target_opts.append('--compilation_mode=opt')

            # select 'opt' config section (this is *not* the same as --compilation_mode=opt!)
            # https://docs.bazel.build/versions/master/user-manual.html#flag--config
            self.target_opts.append('--config=opt')

        # make Bazel print full command line + make it verbose on failures
        # https://docs.bazel.build/versions/master/user-manual.html#flag--subcommands
        # https://docs.bazel.build/versions/master/user-manual.html#flag--verbose_failures
        self.target_opts.extend(['--subcommands', '--verbose_failures'])

        self.target_opts.append(f'--jobs={self.cfg.parallel}')

        if self.toolchain.options.get('pic', None):
            self.target_opts.append('--copt="-fPIC"')

        # include install location of Python packages in $PYTHONPATH,
        # and specify that value of $PYTHONPATH should be passed down into Bazel build environment;
        # this is required to make sure that Python packages included as extensions are found at build time;
        # see also https://github.com/tensorflow/tensorflow/issues/22395
        pythonpath = os.getenv('PYTHONPATH', '')
        action_pythonpath = [os.path.join(self.installdir, self.pylibdir), pythonpath]
        if LooseVersion(self.version) >= LooseVersion('2.14') and 'EBPYTHONPREFIXES' in os.environ:
            # Since TF 2.14 the build uses hermetic python, which ignores sitecustomize.py from EB python;
            # explicity include our site-packages here to respect EBPYTHONPREFIXERS, if that's prefered.
            pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
            eb_pythonpath = os.path.join(os.getenv('EBROOTPYTHON'), 'lib', 'python' + pyshortver, 'site-packages')
            action_pythonpath.append(eb_pythonpath)
        env.setvar('PYTHONPATH', os.pathsep.join(action_pythonpath))

        # Make TF find our modules. LD_LIBRARY_PATH gets automatically added by configure.py
        cpaths, libpaths = self.system_libs_info[1:]
        if cpaths:
            action_env['CPATH'] = ':'.join(cpaths)
        if libpaths:
            action_env['LIBRARY_PATH'] = ':'.join(libpaths)
        action_env['PYTHONPATH'] = INHERIT
        # Also export $EBPYTHONPREFIXES to handle the multi-deps python setup
        # See https://github.com/easybuilders/easybuild-easyblocks/pull/1664
        if 'EBPYTHONPREFIXES' in os.environ:
            action_env['EBPYTHONPREFIXES'] = INHERIT

        # Ignore user environment for Python
        action_env['PYTHONNOUSERSITE'] = '1'

        # TF 2 (final) sets this in configure
        if LooseVersion(self.version) < LooseVersion('2.0'):
            if self._with_cuda:
                self.target_opts.append('--config=cuda')

        # note: using --config=mkl results in a significantly different build, with a different
        # threading model (which may lead to thread oversubscription and significant performance loss,
        # see https://github.com/easybuilders/easybuild-easyblocks/issues/2577) and different
        # runtime behavior w.r.t. GPU vs CPU execution of functions like tf.matmul
        # (see https://github.com/easybuilders/easybuild-easyconfigs/issues/14120),
        # so make sure you really know you want to use this!

        # auto-enable use of MKL-DNN/oneDNN and --config=mkl when possible if with_mkl_dnn is left unspecified;
        # only do this for TensorFlow versions older than 2.4.0, since more recent versions
        # oneDNN is used automatically for x86_64 systems (and mkl-dnn is no longer a dependency);
        if self.cfg['with_mkl_dnn'] is None and LooseVersion(self.version) < LooseVersion('2.4.0'):
            cpu_arch = get_cpu_architecture()
            if cpu_arch == X86_64:
                # Supported on x86 since forever
                self.cfg['with_mkl_dnn'] = True
                self.log.info("Auto-enabled use of MKL-DNN on %s CPU architecture", cpu_arch)
            else:
                self.log.info("Not enabling use of MKL-DNN on %s CPU architecture", cpu_arch)

        # if mkl-dnn is listed as a dependency it is used
        mkl_root = get_software_root('mkl-dnn')
        if mkl_root:
            self.target_opts.append('--config=mkl')
            env.setvar('TF_MKL_ROOT', mkl_root)
        elif self.cfg['with_mkl_dnn']:
            # this makes TensorFlow use mkl-dnn (cfr. https://github.com/01org/mkl-dnn),
            # and download it if needed
            self.target_opts.append('--config=mkl')

        # Use the same configuration (i.e. environment) for compiling and using host tools
        # This means that our action_envs are (almost) always passed
        # Fully removed in Bazel 6.0 and limited effect after at least 3.7 (see --host_action_env)
        if bazel_version < '6.0.0':
            self.target_opts.append('--distinct_host_configuration=false')

        for key, value in sorted(action_env.items()):
            option = key
            if value is not None:
                option += "='%s'" % value

            self.target_opts.append('--action_env=' + option)
            if bazel_version >= '3.7.0':
                # Since Bazel 3.7 action_env only applies to the "target" environment, not the "host" environment
                # As we are not cross-compiling we need both be the same -> Duplicate the setting to host_action_env
                # See https://github.com/bazelbuild/bazel/commit/a463d9095386b22c121d20957222dbb44caef7d4
                self.target_opts.append('--host_action_env=' + option)

        # Compose final command
        cmd = (
            [self.cfg['prebuildopts']]
            + ['bazel']
            + self.bazel_opts
            + ['build']
            + self.target_opts
            + [self.cfg['buildopts']]
            # specify target of the build command as last argument
            + ['//tensorflow/tools/pip_package:build_pip_package']
        )

        with self.set_tmp_dir():
            run_shell_cmd(' '.join(cmd))

            # run generated 'build_pip_package' script to build the .whl
            cmd = "bazel-bin/tensorflow/tools/pip_package/build_pip_package %s" % self.builddir
            run_shell_cmd(cmd)

    def test_step(self):
        """Run TensorFlow unit tests"""
        # IMPORTANT: This code allows experiments with running TF tests but may change
        test_targets = self.cfg['test_targets']
        if not test_targets:
            self.log.info('No targets selected for tests. Set e.g. test_targets = ["//tensorflow/python/..."] '
                          'to run TensorFlow tests.')
            return
        # Allow a string as the test_targets (useful for C&P testing from TF sources)
        if not isinstance(test_targets, list):
            test_targets = test_targets.split(' ')

        test_opts = self.target_opts
        test_opts.append('--test_output=errors')  # (Additionally) show logs from failed tests
        test_opts.append('--build_tests_only')  # Don't build tests which won't be executed

        # determine number of cores/GPUs to use for tests
        max_num_test_jobs = self.cfg['test_max_parallel'] or self.cfg.parallel
        if self._with_cuda:
            if not which('nvidia-smi', on_error=IGNORE):
                print_warning('Could not find nvidia-smi. Assuming a system without GPUs and skipping GPU tests!')
                num_gpus_to_use = 0
            elif os.environ.get('CUDA_VISIBLE_DEVICES') == '-1':
                print_warning('GPUs explicitely disabled via CUDA_VISIBLE_DEVICES. Skipping GPU tests!')
                num_gpus_to_use = 0
            else:
                # determine number of available GPUs via nvidia-smi command, fall back to just 1 GPU
                # Note: Disable checking exit code in run_shell_cmd, and do it explicitly below
                res = run_shell_cmd("nvidia-smi --list-gpus", fail_on_error=False)
                try:
                    if res.exit_code != 0:
                        raise RuntimeError("nvidia-smi returned exit code %s with output:\n%s" % (res.exit_code,
                                                                                                  res.output))
                    else:
                        self.log.info('nvidia-smi succeeded with output:\n%s' % res.output)
                        gpu_ct = sum(line.startswith('GPU ') for line in res.output.strip().split('\n'))
                except (RuntimeError, ValueError) as err:
                    self.log.warning("Failed to get the number of GPUs on this system: %s", err)
                    gpu_ct = 0

                if gpu_ct == 0:
                    print_warning('No GPUs found. Skipping GPU tests!')

                num_gpus_to_use = min(max_num_test_jobs, gpu_ct)

            # Can (likely) only run 1 test per GPU but don't need to limit CPU tests
            num_test_jobs = {
                CPU_DEVICE: max_num_test_jobs,
                GPU_DEVICE: num_gpus_to_use,
            }
        else:
            num_test_jobs = {
                CPU_DEVICE: max_num_test_jobs,
                GPU_DEVICE: 0,
            }

        cfg_testopts = {
            CPU_DEVICE: self.cfg['testopts'],
            GPU_DEVICE: self.cfg['testopts_gpu'],
        }

        devices = [CPU_DEVICE]
        # Skip GPU tests if not build with CUDA or no test jobs set (e.g. due to no GPUs available)
        if self._with_cuda and num_test_jobs[GPU_DEVICE]:
            devices.append(GPU_DEVICE)

        for device in devices:
            # Determine tests to run
            test_tag_filters_name = 'test_tag_filters_' + device
            test_tag_filters = self.cfg[test_tag_filters_name]
            if not test_tag_filters:
                self.log.info('Skipping %s test because %s is not set', device, test_tag_filters_name)
                continue
            else:
                self.log.info('Starting %s test', device)

            current_test_opts = test_opts[:]
            current_test_opts.append('--local_test_jobs=%s' % num_test_jobs[device])

            # Add both build and test tag filters as done by the TF CI scripts
            current_test_opts.extend("--%s_tag_filters='%s'" % (step, test_tag_filters) for step in ('test', 'build'))

            # Disable all GPUs for the CPU tests, by setting $CUDA_VISIBLE_DEVICES to -1,
            # otherwise TensorFlow will still use GPUs and fail.
            # Only tests explicitely marked with the 'gpu' tag can run with GPUs visible;
            # see https://github.com/tensorflow/tensorflow/issues/45664
            if device == CPU_DEVICE:
                current_test_opts.append("--test_env=CUDA_VISIBLE_DEVICES='-1'")
            else:
                # Propagate those environment variables to the GPU tests if they are set
                important_cuda_env_vars = (
                    'CUDA_CACHE_DISABLE',
                    'CUDA_CACHE_MAXSIZE',
                    'CUDA_CACHE_PATH',
                    'CUDA_FORCE_PTX_JIT',
                    'CUDA_DISABLE_PTX_JIT'
                )
                current_test_opts.extend(
                    '--test_env=' + var_name
                    for var_name in important_cuda_env_vars
                    if var_name in os.environ
                )

                # These are used by the `parallel_gpu_execute` helper script from TF
                current_test_opts.append('--test_env=TF_GPU_COUNT=%s' % num_test_jobs[GPU_DEVICE])
                current_test_opts.append('--test_env=TF_TESTS_PER_GPU=1')

            # Append user specified options last
            current_test_opts.append(cfg_testopts[device])

            # Compose final command
            cmd = ' '.join(
                [self.cfg['pretestopts']]
                + ['bazel']
                + self.bazel_opts
                + ['test']
                + current_test_opts
                + ['--']
                # specify targets to test as last argument
                + test_targets
            )

            with self.set_tmp_dir():
                res = run_shell_cmd(cmd, fail_on_error=False)
            if res.exit_code:
                fail_msg = 'Tests on %s (cmd: %s) failed with exit code %s and output:\n%s' % (
                    device, cmd, res.exit_code, res.output)
                self.log.warning(fail_msg)
                # Try to enhance error message
                failed_tests = []
                failed_test_logs = dict()
                # Bazel outputs failed tests like "//tensorflow/c:kernels_test   FAILED in[...]"
                for match in re.finditer(r'^(//[a-zA-Z_/:]+)\s+FAILED', res.output, re.MULTILINE):
                    test_name = match.group(1)
                    failed_tests.append(test_name)
                    # Logs are in a folder named after the test, e.g. tensorflow/c/kernels_test
                    test_folder = test_name[2:].replace(':', '/')
                    # Example file names:
                    # <prefix>/k8-opt/testlogs/tensorflow/c/kernels_test/test.log
                    # <prefix>/k8-opt/testlogs/tensorflow/c/kernels_test/shard_1_of_4/test_attempts/attempt_1.log
                    test_log_re = re.compile(r'.*\n(.*\n)?\s*(/.*/testlogs/%s/(/[^/]*)?test.log)' % test_folder)
                    log_match = test_log_re.match(res.output, match.end())
                    if log_match:
                        failed_test_logs[test_name] = log_match.group(2)
                # When TF logs are found enhance the below error by additionally logging the details about failed tests
                for test_name, log_path in failed_test_logs.items():
                    if os.path.exists(log_path):
                        self.log.warning('Test %s failed with output\n%s', test_name,
                                         read_file(log_path, log_error=False))
                if failed_tests:
                    failed_tests = sorted(set(failed_tests))  # Make unique to not count retries
                    fail_msg = 'At least %s %s tests failed:\n%s' % (
                        len(failed_tests), device, ', '.join(failed_tests))
                self.report_test_failure(fail_msg)
            else:
                self.log.info('Tests on %s succeeded with output:\n%s', device, res.output)

    def install_step(self):
        """Custom install procedure for TensorFlow."""
        # find .whl file that was built, and install it using 'pip install'
        if "-rc" in self.version:
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

            run_shell_cmd(cmd)
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
        if self.python_cmd is None:
            self.prepare_python()

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
                run_shell_cmd(cmd)

            # run test script (if any)
            if self.test_script:
                # copy test script to build dir before running it, to avoid that a file named 'tensorflow.py'
                # (a customized TensorFlow easyblock for example) breaks 'import tensorflow'
                test_script = os.path.join(self.builddir, os.path.basename(self.test_script))
                copy_file(self.test_script, test_script)

                run_shell_cmd("python %s" % test_script)

        return res
