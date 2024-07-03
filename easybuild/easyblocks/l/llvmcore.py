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
EasyBuild support for building and installing LLVM, implemented as an easyblock

@author: Simon Branford (University of Birmingham)
@author: Kenneth Hoste (Ghent University)
@author: Davide Grassano (CECAM HQ - Lausanne)
"""
import glob
import os
import re

from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion, run
from easybuild.tools.build_log import EasyBuildError, print_msg, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.environment import setvar
from easybuild.tools.filetools import (apply_regex_substitutions, change_dir,
                                       mkdir, symlink, which)
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import (get_cpu_architecture,
                                         get_shared_lib_ext)
from easybuild.tools.toolchain.toolchain import Toolchain

from easybuild.easyblocks.clang import CLANG_TARGETS, DEFAULT_TARGETS_MAP
from easybuild.easyblocks.generic.cmakemake import CMakeMake

remove_gcc_opts = {

    'LIBCXX_USE_COMPILER_RT': 'On',
    'LIBCXX_CXX_ABI': 'libcxxabi',

    'LIBCXXABI_USE_LLVM_UNWINDER': 'On',
    'LIBCXXABI_USE_COMPILER_RT': 'On',

    'LIBUNWIND_USE_COMPILER_RT': 'On',

    'SANITIZER_USE_STATIC_LLVM_UNWINDER': 'On',
    'COMPILER_RT_USE_LIBCXX': 'On',
    'COMPILER_RT_USE_LLVM_UNWINDER': 'On',
    'COMPILER_RT_USE_BUILTINS_LIBRARY': 'On',
    'COMPILER_RT_ENABLE_STATIC_UNWINDER': 'On',  # https://lists.llvm.org/pipermail/llvm-bugs/2016-July/048424.html
    'COMPILER_RT_ENABLE_INTERNAL_SYMBOLIZER': 'On',
    'COMPILER_RT_BUILD_GWP_ASAN': 'Off',

    'CLANG_DEFAULT_CXX_STDLIB': 'libc++',
    'CLANG_DEFAULT_RTLIB': 'compiler-rt',
    'CLANG_DEFAULT_LINKER': 'lld',
    'CLANG_DEFAULT_UNWINDLIB': 'libunwind',

    'LIBCXX_HAS_GCC_S_LIB': 'Off',
    'LIBCXXABI_HAS_GCC_S_LIB': 'Off',
    'LIBUNWIND_HAS_GCC_S_LIB': 'Off',

    # Libxml2 from system gets autmatically detected and linked in bringing dependencies from stdc++, gcc_s, icuuc, etc
    'LLVM_ENABLE_LIBXML2': 'Off',
}

disable_werror = {
    'LLVM_ENABLE_WERROR': 'Off',
    'BENCHMARK_ENABLE_WERROR': 'Off',
    'COMPILER_RT_ENABLE_WERROR': 'Off',
    'LIBC_WNO_ERROR': 'On',
    'LIBCXX_ENABLE_WERROR': 'Off',
    'LIBUNWIND_ENABLE_WERROR': 'Off',
    'OPENMP_ENABLE_WERROR': 'Off',
    'FLANG_ENABLE_WERROR': 'Off',
}

general_opts = {
    # If EB is launched from a venv, avoid giving priority to the venv's python
    'Python3_FIND_VIRTUALENV': 'STANDARD',
    'LLVM_INSTALL_UTILS': 'ON',
    'LLVM_INCLUDE_BENCHMARKS': 'OFF',
    'CMAKE_VERBOSE_MAKEFILE': 'ON',
}


class EB_LLVMcore(CMakeMake):
    """
    Support for building and installing LLVM
    """

    @staticmethod
    def extra_options():
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'assertions': [False, "Enable assertions.  Helps to catch bugs in Clang.", CUSTOM],
            'build_targets': [None, "Build targets for LLVM (host architecture if None). Possible values: " +
                                    ', '.join(CLANG_TARGETS), CUSTOM],
            'bootstrap': [True, "Build LLVM-Clang using itself", CUSTOM],
            'full_llvm': [True, "Build LLVM without any dependency", CUSTOM],
            'enable_rtti': [True, "Enable RTTI", CUSTOM],
            'skip_all_tests': [False, "Skip running of tests", CUSTOM],
            'skip_sanitizer_tests': [True, "Do not run the sanitizer tests", CUSTOM],
            'python_bindings': [False, "Install python bindings", CUSTOM],
            'build_clang_extras': [False, "Build the LLVM Clang extra tools", CUSTOM],
            'build_bolt': [False, "Build the LLVM bolt binary optimizer", CUSTOM],
            'build_lld': [False, "Build the LLVM lld linker", CUSTOM],
            'build_lldb': [False, "Build the LLVM lldb debugger", CUSTOM],
            'build_runtimes': [True, "Build the LLVM runtimes (compiler-rt, libunwind, libcxx, libcxxabi)", CUSTOM],
            'build_openmp': [True, "Build the LLVM OpenMP runtime", CUSTOM],
            'usepolly': [False, "Build Clang with polly", CUSTOM],
            'disable_werror': [False, "Disable -Werror for all projects", CUSTOM],
            'test_suite_max_failed': [0, "Maximum number of failing tests (does not count allowed failures)", CUSTOM],
        })

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize LLVM-specific variables."""
        super(EB_LLVMcore, self).__init__(*args, **kwargs)

        if LooseVersion(self.version) < LooseVersion('18.1.6'):
            raise EasyBuildError("LLVM version %s is not supported, please use version 18.1.6 or newer", self.version)

        self.llvm_src_dir = None
        self.llvm_obj_dir_stage1 = None
        self.llvm_obj_dir_stage2 = None
        self.llvm_obj_dir_stage3 = None
        self.intermediate_projects = ['llvm', 'clang']
        self.intermediate_runtimes = ['compiler-rt', 'libunwind', 'libcxx', 'libcxxabi']
        self.final_projects = ['llvm', 'mlir', 'clang', 'flang']
        self.final_runtimes = []

        # Shared
        self.build_shared = self.cfg.get('build_shared_libs', False)
        if self.build_shared:
            self.cfg['build_shared_libs'] = None
            general_opts['LLVM_BUILD_LLVM_DYLIB'] = 'ON'
            general_opts['LLVM_LINK_LLVM_DYLIB'] = 'ON'
            general_opts['LIBCXX_ENABLE_SHARED'] = 'ON'
            general_opts['LIBCXXABI_ENABLE_SHARED'] = 'ON'
            general_opts['LIBUNWIND_ENABLE_SHARED'] = 'ON'
        else:
            general_opts['LLVM_BUILD_LLVM_DYLIB'] = 'OFF'
            general_opts['LLVM_LINK_LLVM_DYLIB'] = 'OFF'
            general_opts['LIBCXX_ENABLE_SHARED'] = 'OFF'
            general_opts['LIBCXXABI_ENABLE_SHARED'] = 'OFF'
            general_opts['LIBUNWIND_ENABLE_SHARED'] = 'OFF'
            general_opts['LIBCXX_ENABLE_STATIC'] = 'ON'
            general_opts['LIBCXXABI_ENABLE_STATIC'] = 'ON'
            general_opts['LIBUNWIND_ENABLE_STATIC'] = 'ON'

        # RTTI
        if self.cfg["enable_rtti"]:
            general_opts['LLVM_REQUIRES_RTTI'] = 'ON'
            general_opts['LLVM_ENABLE_RTTI'] = 'ON'
            # Does not work with Flang
            # general_opts['LLVM_ENABLE_EH'] = 'ON'

        self.full_llvm = self.cfg['full_llvm']

        # Other vustom options
        if self.full_llvm:
            if not self.cfg['bootstrap']:
                raise EasyBuildError("Full LLVM build irequires bootstrap build")
            if not self.cfg['build_lld']:
                raise EasyBuildError("Full LLVM build requires building lld")
            if not self.cfg['build_runtimes']:
                raise EasyBuildError("Full LLVM build requires building runtimes")
            self.log.info("Building LLVM without any GCC dependency")

        if self.cfg['disable_werror']:
            general_opts.update(disable_werror)
        if self.cfg['build_runtimes']:
            self.final_runtimes += ['compiler-rt', 'libunwind', 'libcxx', 'libcxxabi']
        if self.cfg['build_openmp']:
            self.final_projects.append('openmp')
        if self.cfg['usepolly']:
            self.final_projects.append('polly')
        if self.cfg['build_clang_extras']:
            self.final_projects.append('clang-tools-extra')
        if self.cfg['build_lld']:
            self.intermediate_projects.append('lld')
            self.final_projects.append('lld')
        if self.cfg['build_lldb']:
            self.final_projects.append('lldb')
            if self.full_llvm:
                remove_gcc_opts['LLDB_ENABLE_LIBXML2'] = 'Off'
                remove_gcc_opts['LLDB_ENABLE_LZMA'] = 'Off'
                remove_gcc_opts['LLDB_ENABLE_PYTHON'] = 'Off'
        if self.cfg['build_bolt']:
            self.final_projects.append('bolt')

        # Build targets
        build_targets = self.cfg['build_targets']
        if build_targets is None:
            arch = get_cpu_architecture()
            try:
                default_targets = DEFAULT_TARGETS_MAP[arch][:]
                self.cfg['build_targets'] = build_targets = default_targets
                self.log.debug("Using %s as default build targets for CPU architecture %s.", default_targets, arch)
            except KeyError:
                raise EasyBuildError("No default build targets defined for CPU architecture %s.", arch)

        unknown_targets = [target for target in build_targets if target not in CLANG_TARGETS]

        if unknown_targets:
            raise EasyBuildError("Some of the chosen build targets (%s) are not in %s.",
                                 ', '.join(unknown_targets), ', '.join(CLANG_TARGETS))
        self.build_targets = build_targets or []

        general_opts['CMAKE_BUILD_TYPE'] = self.build_type
        general_opts['CMAKE_INSTALL_PREFIX'] = self.installdir
        if self.toolchain.options['pic']:
            general_opts['CMAKE_POSITION_INDEPENDENT_CODE'] = 'ON'

        general_opts['LLVM_TARGETS_TO_BUILD'] = ';'.join(build_targets)

        self._cmakeopts = {}
        self._cfgopts = list(filter(None, self.cfg.get('configopts', '').split()))
        self.llvm_src_dir = os.path.join(self.builddir, 'llvm-project-%s.src' % self.version)

    def _configure_general_build(self):
        """General configuration step for LLVM."""
        self._cmakeopts['LLVM_ENABLE_ASSERTIONS'] = 'ON' if self.cfg['assertions'] else 'OFF'

        if get_software_root('zlib'):
            self._cmakeopts['LLVM_ENABLE_ZLIB'] = 'ON'

        z3_root = get_software_root("Z3")
        if z3_root:
            self._cmakeopts['LLVM_ENABLE_Z3_SOLVER'] = 'ON'
            self._cmakeopts['LLVM_Z3_INSTALL_DIR'] = z3_root

        self._cmakeopts.update(general_opts)

    def _configure_intermediate_build(self):
        """Configure the intermediate stages of the build."""
        self._cmakeopts['LLVM_ENABLE_PROJECTS'] = '"%s"' % ';'.join(self.intermediate_projects)
        self._cmakeopts['LLVM_ENABLE_RUNTIMES'] = '"%s"' % ';'.join(self.intermediate_runtimes)

    def _configure_final_build(self):
        """Configure the final stage of the build."""
        self._cmakeopts['LLVM_ENABLE_PROJECTS'] = '"%s"' % ';'.join(self.final_projects)
        self._cmakeopts['LLVM_ENABLE_RUNTIMES'] = '"%s"' % ';'.join(self.final_runtimes)

        hwloc_root = get_software_root('hwloc')
        if hwloc_root:
            self.log.info("Using %s as hwloc root", hwloc_root)
            self._cmakeopts['LIBOMP_USE_HWLOC'] = 'ON'
            self._cmakeopts['LIBOMP_HWLOC_INSTALL_DIR'] = hwloc_root

        if 'openmp' in self.final_projects:
            self._cmakeopts['LIBOMP_INSTALL_ALIASES'] = 'OFF'

        # Make sure tests are not running with more than `--parallel` tasks
        self._cmakeopts['LLVM_LIT_ARGS'] = '"-j %s"' % self.cfg['parallel']
        if self.cfg['usepolly']:
            self._cmakeopts['LLVM_POLLY_LINK_INTO_TOOLS'] = 'ON'
        if not self.cfg['skip_all_tests']:
            self._cmakeopts['LLVM_INCLUDE_TESTS'] = 'ON'
            self._cmakeopts['LLVM_BUILD_TESTS'] = 'ON'

    def configure_step(self):
        """
        Install extra tools in bin/; enable zlib if it is a dep; optionally enable rtti; and set the build target
        """
        # Parallel build
        self.make_parallel_opts = ""
        if self.cfg['parallel']:
            self.make_parallel_opts = "-j %s" % self.cfg['parallel']

        # Bootstrap
        self.llvm_obj_dir_stage1 = os.path.join(self.builddir, 'llvm.obj.1')
        if self.cfg['bootstrap']:
            self.log.info("Initialising for bootstrap build.")
            self.llvm_obj_dir_stage2 = os.path.join(self.builddir, 'llvm.obj.2')
            self.llvm_obj_dir_stage3 = os.path.join(self.builddir, 'llvm.obj.3')
            self.final_dir = self.llvm_obj_dir_stage3
            mkdir(self.llvm_obj_dir_stage2)
            mkdir(self.llvm_obj_dir_stage3)
        else:
            self.log.info("Initialising for single stage build.")
            self.final_dir = self.llvm_obj_dir_stage1

        xml2_root = get_software_root('libxml2')
        if xml2_root:
            if self.full_llvm:
                self.log.warning("LLVM is being built in `full_llvm` mode, libxml2 will not be used")
            else:
                self._cmakeopts['LLVM_ENABLE_LIBXML2'] = 'ON'
                # self._cmakeopts['LIBXML2_ROOT'] = xml2_root

        lit_root = get_software_root('lit')
        if not lit_root:
            if not self.cfg['skip_all_tests']:
                raise EasyBuildError("Can't find `lit`, needed for running tests-suite")

        gcc_version = get_software_version('GCCcore')
        if LooseVersion(gcc_version) < LooseVersion('13'):
            raise EasyBuildError("LLVM %s requires GCC 13 or newer, found %s", self.version, gcc_version)

        self.llvm_obj_dir_stage1 = os.path.join(self.builddir, 'llvm.obj.1')
        if self.cfg['bootstrap']:
            self._configure_intermediate_build()
            # if self.full_llvm:
            #     self.intermediate_projects.append('libc')
            #     self.final_projects.append('libc')
        else:
            self._configure_final_build()
            self.final_dir = self.llvm_obj_dir_stage1

        if self.cfg['skip_sanitizer_tests'] and build_option('strict') != run.ERROR:
            self.log.debug("Disabling the sanitizer tests")
            self.disable_sanitizer_tests()

        # Remove python bindings tests causing uncaught exception in the build
        cmakelists_tests = os.path.join(self.llvm_src_dir, 'clang', 'CMakeLists.txt')
        regex_subs = []
        regex_subs.append((r'add_subdirectory\(bindings/python/tests\)', ''))
        apply_regex_substitutions(cmakelists_tests, regex_subs)

        gcc_prefix = get_software_root('GCCcore')
        # If that doesn't work, try with GCC
        if gcc_prefix is None:
            gcc_prefix = get_software_root('GCC')
        # If that doesn't work either, print error and exit
        if gcc_prefix is None:
            raise EasyBuildError("Can't find GCC or GCCcore to use")
        self._cmakeopts['GCC_INSTALL_PREFIX'] = gcc_prefix
        self.log.debug("Using %s as GCC_INSTALL_PREFIX", gcc_prefix)

        # Disable OpenMP offload support if not building for NVPTX or AMDGPU
        if 'NVPTX' not in self.build_targets and 'AMDGPU' not in self.build_targets:
            general_opts['OPENMP_ENABLE_LIBOMPTARGET'] = 'OFF'

        # If 'NVPTX' is in the build targets we assume the user would like OpenMP offload support as well
        if 'NVPTX' in self.build_targets:
            # list of CUDA compute capabilities to use can be specifed in two ways (where (2) overrules (1)):
            # (1) in the easyconfig file, via the custom cuda_compute_capabilities;
            # (2) in the EasyBuild configuration, via --cuda-compute-capabilities configuration option;
            ec_cuda_cc = self.cfg['cuda_compute_capabilities']
            cfg_cuda_cc = build_option('cuda_compute_capabilities')
            cuda_cc = cfg_cuda_cc or ec_cuda_cc or []
            if not cuda_cc:
                raise EasyBuildError("Can't build Clang with CUDA support "
                                     "without specifying 'cuda-compute-capabilities'")
            default_cc = self.cfg['default_cuda_capability'] or min(cuda_cc)
            if not self.cfg['default_cuda_capability']:
                print_warning("No default CUDA capability defined! "
                              "Using '%s' taken as minimum from 'cuda_compute_capabilities'" % default_cc)
            cuda_cc = [cc.replace('.', '') for cc in cuda_cc]
            default_cc = default_cc.replace('.', '')
            general_opts['LIBOMPTARGET_DEVICE_ARCHITECTURES'] = 'sm_%s' % default_cc
            # OLD (pre v16) flags
            general_opts['CLANG_OPENMP_NVPTX_DEFAULT_ARCH'] = 'sm_%s' % default_cc
            general_opts['LIBOMPTARGET_NVPTX_COMPUTE_CAPABILITIES'] = ','.join(cuda_cc)
        # If we don't want to build with CUDA (not in dependencies) trick CMakes FindCUDA module into not finding it by
        # using the environment variable which is used as-is and later checked for a falsy value when determining
        # whether CUDA was found
        if not get_software_root('CUDA'):
            setvar('CUDA_NVCC_EXECUTABLE', 'IGNORE')
        # If 'AMDGPU' is in the build targets we assume the user would like OpenMP offload support for AMD
        if 'AMDGPU' in self.build_targets:
            if not get_software_root('ROCR-Runtime'):
                raise EasyBuildError("Can't build Clang with AMDGPU support "
                                     "without dependency 'ROCR-Runtime'")
            ec_amdgfx = self.cfg['amd_gfx_list']
            if not ec_amdgfx:
                raise EasyBuildError("Can't build Clang with AMDGPU support "
                                     "without specifying 'amd_gfx_list'")
            general_opts['LIBOMPTARGET_AMDGCN_GFXLIST'] = ' '.join(ec_amdgfx)

        self._configure_general_build()

        self.add_cmake_opts()
        super(EB_LLVMcore, self).configure_step(
            builddir=self.llvm_obj_dir_stage1,
            srcdir=os.path.join(self.llvm_src_dir, "llvm")
            )

    def disable_sanitizer_tests(self):
        """Disable the tests of all the sanitizers by removing the test directories from the build system"""

        # In Clang 3.6, the sanitizer tests are grouped together in one CMakeLists
        # We patch out adding the subdirectories with the sanitizer tests
        cmakelists_tests = os.path.join(self.llvm_src_dir, 'compiler-rt', 'test', 'CMakeLists.txt')
        regex_subs = []
        regex_subs.append((r'compiler_rt_test_runtime.*san.*', ''))

        apply_regex_substitutions(cmakelists_tests, regex_subs)

    def add_cmake_opts(self):
        """Add LLVM-specific CMake options."""
        base_opts = self._cfgopts.copy()
        for k, v in self._cmakeopts.items():
            base_opts.append('-D%s=%s' % (k, v))
        self.cfg['configopts'] = ' '.join(base_opts)

        # self.log.debug("-%"*50)
        # self.log.debug("Using %s as configopts", self._cfgopts)
        # self.log.debug("Using %s as cmakeopts", self._cmakeopts)
        # self.log.debug("-%"*50)

    def configure_step2(self):
        """Configure the second stage of the bootstrap."""
        self._cmakeopts = {}
        self._configure_general_build()
        self._configure_intermediate_build()
        if self.full_llvm:
            self._cmakeopts.update(remove_gcc_opts)

    def configure_step3(self):
        """Configure the third stage of the bootstrap."""
        self._cmakeopts = {}
        self._configure_general_build()
        self._configure_final_build()
        if self.full_llvm:
            self._cmakeopts.update(remove_gcc_opts)

    def build_with_prev_stage(self, prev_dir, stage_dir):
        """Build LLVM using the previous stage."""
        curdir = os.getcwd()
        orig_path = os.getenv('PATH')
        # orig_library_path = os.getenv('LIBRARY_PATH')
        orig_ld_library_path = os.getenv('LD_LIBRARY_PATH')

        self._cmakeopts['CMAKE_C_COMPILER'] = os.path.join(prev_dir, 'bin/clang')
        self._cmakeopts['CMAKE_CXX_COMPILER'] = os.path.join(prev_dir, 'bin/clang++')
        self._cmakeopts['CMAKE_ASM_COMPILER'] = os.path.join(prev_dir, 'bin/clang')
        self._cmakeopts['CMAKE_ASM_COMPILER_ID'] = 'Clang'

        self.add_cmake_opts()

        bin_dir = os.path.join(prev_dir, 'bin')
        lib_dir_runtime = self.get_runtime_lib_path(prev_dir, fail_ok=False)

        # Give priority to the libraries in the current stage if compiled to avoid failures due to undefined symbols
        # e.g. when calling the compiled clang-ast-dump for stage 3
        lib_path = ':'.join([
            # curr_lib_dir,
            os.path.join(stage_dir, lib_dir_runtime),
            # prev_lib_dir,
            os.path.join(prev_dir, lib_dir_runtime),
        ])

        # Needed for passing the variables to the build command
        setvar('PATH', bin_dir + ":" + orig_path)
        setvar('LD_LIBRARY_PATH', lib_path + ":" + orig_ld_library_path)

        # If building with rpath, create RPATH wrappers for the Clang compilers for stage 2 and 3
        if build_option('rpath'):
            my_toolchain = Toolchain(name='llvm', version='1')
            my_toolchain.prepare_rpath_wrappers()
            self.log.info("Prepared rpath wrappers")

            # add symlink for 'opt' to wrapper dir, since Clang expects it in the same directory
            # see https://github.com/easybuilders/easybuild-easyblocks/issues/3075
            clang_wrapper_dir = os.path.dirname(which('clang'))
            symlink(os.path.join(prev_dir, 'opt'), os.path.join(clang_wrapper_dir, 'opt'))

            # RPATH wrappers add -Wl,rpath arguments to all command lines, including when it is just compiling
            # Clang by default warns about that, and then some configure tests use -Werror which turns those warnings
            # into errors. As a result, those configure tests fail, even though the compiler supports the requested
            # functionality (e.g. the test that checks if -fPIC is supported would fail, and it compiles without
            # resulting in relocation errors).
            # See https://github.com/easybuilders/easybuild-easyblocks/pull/2799#issuecomment-1270621100
            # Here, we add -Wno-unused-command-line-argument to CXXFLAGS to avoid these warnings alltogether
            cflags = os.getenv('CFLAGS')
            cxxflags = os.getenv('CXXFLAGS')
            setvar('CFLAGS', "%s %s" % (cflags, '-Wno-unused-command-line-argument'))
            setvar('CXXFLAGS', "%s %s" % (cxxflags, '-Wno-unused-command-line-argument'))

        change_dir(stage_dir)
        self.log.debug("Configuring %s", stage_dir)
        cmd = "cmake %s %s" % (self.cfg['configopts'], os.path.join(self.llvm_src_dir, 'llvm'))
        run_cmd(cmd, log_all=True)

        self.log.debug("Building %s", stage_dir)
        cmd = "make %s VERBOSE=1" % self.make_parallel_opts
        run_cmd(cmd, log_all=True)

        change_dir(curdir)
        setvar('PATH', orig_path)
        setvar('LD_LIBRARY_PATH', orig_ld_library_path)

    def build_step(self, verbose=False, path=None):
        """Build LLVM, and optionally build it using itself."""
        if self.cfg['bootstrap']:
            self.log.info("Building stage 1")
            print_msg("Building stage 1/3")
        else:
            self.log.info("Building LLVM")
            print_msg("Building stage 1/1")
        change_dir(self.llvm_obj_dir_stage1)
        super(EB_LLVMcore, self).build_step(verbose, path)
        # import shutil
        # change_dir(self.builddir)
        # print_msg("TESTING!!!: Copying from previosu build (REMOVE ME)")
        # shutil.rmtree('llvm.obj.1', ignore_errors=True)
        # shutil.copytree(os.path.join('..', 'llvm.obj.1'), 'llvm.obj.1')
        if self.cfg['bootstrap']:
            self.log.info("Building stage 2")
            print_msg("Building stage 2/3")
            self.configure_step2()
            self.build_with_prev_stage(self.llvm_obj_dir_stage1, self.llvm_obj_dir_stage2)
            # change_dir(self.builddir)
            # print_msg("TESTING!!!: Copying from previosu build (REMOVE ME)")
            # shutil.rmtree('llvm.obj.2', ignore_errors=True)
            # shutil.copytree(os.path.join('..', 'llvm.obj.2'), 'llvm.obj.2')

            self.log.info("Building stage 3")
            print_msg("Building stage 3/3")
            self.configure_step3()
            self.build_with_prev_stage(self.llvm_obj_dir_stage2, self.llvm_obj_dir_stage3)
            # change_dir(self.builddir)
            # print_msg("TESTING!!!: Copying from previosu build (REMOVE ME)")
            # shutil.rmtree('llvm.obj.3', ignore_errors=True)
            # shutil.copytree(os.path.join('..', 'llvm.obj.3'), 'llvm.obj.3')

    def _test_step(self, parallel=1):
        """Run test suite with the specified number of parallel jobs for make."""
        basedir = self.final_dir

        change_dir(basedir)
        orig_path = os.getenv('PATH')
        orig_ld_library_path = os.getenv('LD_LIBRARY_PATH')
        # lib_dir = os.path.join(basedir, 'lib')
        lib_dir_runtime = self.get_runtime_lib_path(basedir, fail_ok=False)
        lib_path = ':'.join([os.path.join(basedir, lib_dir_runtime), orig_ld_library_path])
        setvar('PATH', os.path.join(basedir, 'bin') + ":" + orig_path)
        setvar('LD_LIBRARY_PATH', lib_path)

        cmd = "make -j %s check-all" % parallel
        (out, _) = run_cmd(cmd, log_all=False, log_ok=False, simple=False, regexp=False)
        self.log.debug(out)

        setvar('PATH', orig_path)
        setvar('LD_LIBRARY_PATH', orig_ld_library_path)

        rgx_failed = re.compile(r'^ +Failed +: +([0-9]+)', flags=re.MULTILINE)
        mch = rgx_failed.search(out)
        if mch is None:
            rgx_passed = re.compile(r'^ +Passed +: +([0-9]+)', flags=re.MULTILINE)
            mch = rgx_passed.search(out)
            if mch is None:
                num_failed = None
            else:
                num_failed = 0
        else:
            num_failed = int(mch.group(1))

        return num_failed

    def test_step(self):
        """Run Clang tests on final stage (unless disabled)."""
        if not self.cfg['skip_all_tests']:
            self.log.info("Running test-suite with parallel jobs")
            num_failed = self._test_step(parallel=self.cfg['parallel'])
            if num_failed is None:
                self.log.warning("Tests with parallel jobs failed, retrying with single job")
                num_failed = self._test_step(parallel=1)
            if num_failed is None:
                raise EasyBuildError("Failed to extract test results from output")

            if num_failed > self.cfg['test_suite_max_failed']:
                raise EasyBuildError("Too many failed tests: %s", num_failed)

    def install_step(self):
        """Install stage 1 or 3 (if bootsrap) binaries."""
        basedir = self.final_dir
        change_dir(basedir)

        orig_ld_library_path = os.getenv('LD_LIBRARY_PATH')
        lib_dir_runtime = self.get_runtime_lib_path(basedir, fail_ok=False)

        # Give priority to the libraries in the current stage if compiled to avoid failures due to undefined symbols
        # e.g. when calling the compiled clang-ast-dump for stage 3
        lib_path = ':'.join([
            basedir,
            os.path.join(basedir, lib_dir_runtime),
        ])

        # _preinstallopts = self.cfg.get('preinstallopts', '')
        self.cfg.update('preinstallopts', ' '.join([
            'LD_LIBRARY_PATH=%s:%s' % (lib_path, orig_ld_library_path)
        ]))

        super(EB_LLVMcore, self).install_step()

    def get_runtime_lib_path(self, base_dir, fail_ok=True):
        """Return the path to the runtime libraries."""
        arch = get_cpu_architecture()
        glob_pattern = os.path.join(base_dir, 'lib', '%s-*' % arch)
        matches = glob.glob(glob_pattern)
        if matches:
            directory = os.path.basename(matches[0])
            res = os.path.join("lib", directory)
        else:
            if not fail_ok:
                raise EasyBuildError("Could not find runtime library directory")
            print_warning("Could not find runtime library directory")
            res = "lib"

        return res

    def sanity_check_step(self, custom_paths=None, custom_commands=None, extension=False, extra_modules=None):
        self.get_runtime_lib_path(self.installdir, fail_ok=False)
        shlib_ext = get_shared_lib_ext()

        if self.build_shared:
            if custom_paths is None:
                custom_paths = {}
            ptr = custom_paths.setdefault('files', [])
            for lib in ['LLVM', 'MLIR', 'clang', 'clang-cpp', 'lldb']:
                ptr.append(os.path.join('lib', 'lib%s.%s' % (lib, shlib_ext)))

        return super().sanity_check_step(custom_paths=None, custom_commands=None, extension=False, extra_modules=None)

    def make_module_extra(self):
        """Custom variables for Clang module."""
        txt = super(EB_LLVMcore, self).make_module_extra()
        # we set the symbolizer path so that asan/tsan give meanfull output by default
        asan_symbolizer_path = os.path.join(self.installdir, 'bin', 'llvm-symbolizer')
        txt += self.module_generator.set_environment('ASAN_SYMBOLIZER_PATH', asan_symbolizer_path)
        if self.cfg['python_bindings']:
            txt += self.module_generator.prepend_paths('PYTHONPATH', os.path.join("lib", "python"))
        return txt

    def make_module_req_guess(self):
        """
        Clang can find its own headers and libraries but the .so's need to be in LD_LIBRARY_PATH
        """
        runtime_lib_path = self.get_runtime_lib_path(self.installdir, fail_ok=False)
        guesses = super(EB_LLVMcore, self).make_module_req_guess()
        guesses.update({
            'CPATH': [],
            'LIBRARY_PATH': ['lib', 'lib64', runtime_lib_path],
            'LD_LIBRARY_PATH': ['lib', 'lib64', runtime_lib_path],
        })
        return guesses
