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

@author: Dmitri Gribenko (National Technical University of Ukraine "KPI")
@author: Ward Poelmans (Ghent University)
@author: Alan O'Cais (Juelich Supercomputing Centre)
@author: Maxime Boissonneault (Digital Research Alliance of Canada, Universite Laval)
@author: Simon Branford (University of Birmingham)
@author: Kenneth Hoste (Ghent University)
@author: Davide Grassano (CECAM HQ - Lausanne)
"""
import contextlib
import glob
import os
import re
import shutil

from easybuild.framework.easyconfig import CUSTOM
from easybuild.toolchains.compiler.clang import Clang
from easybuild.tools import LooseVersion, run
from easybuild.tools.build_log import EasyBuildError, print_msg, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.environment import setvar
from easybuild.tools.filetools import (apply_regex_substitutions, change_dir,
                                       mkdir, symlink, which)
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import (AARCH32, AARCH64, POWER, RISCV64,
                                         X86_64, get_cpu_architecture,
                                         get_shared_lib_ext)

from easybuild.easyblocks.generic.cmakemake import CMakeMake

LLVM_TARGETS = [
    'AArch64', 'AMDGPU', 'ARM', 'AVR', 'BPF', 'Hexagon', 'Lanai', 'LoongArch', 'Mips', 'MSP430', 'NVPTX', 'PowerPC',
    'RISCV', 'Sparc', 'SystemZ', 'VE', 'WebAssembly', 'X86', 'XCore',
    'all'
]
LLVM_EXPERIMENTAL_TARGETS = [
    'ARC', 'CSKY', 'DirectX', 'M68k', 'SPIRV', 'Xtensa',
]
ALL_TARGETS = LLVM_TARGETS + LLVM_EXPERIMENTAL_TARGETS

DEFAULT_TARGETS_MAP = {
    AARCH32: ['ARM'],
    AARCH64: ['AArch64'],
    POWER: ['PowerPC'],
    RISCV64: ['RISCV'],
    X86_64: ['X86'],
}

AMDGPU_GFX_SUPPORT = [
    'gfx700', 'gfx701', 'gfx801', 'gfx803', 'gfx900', 'gfx902', 'gfx906', 'gfx908', 'gfx90a', 'gfx90c',
    'gfx940', 'gfx941', 'gfx942', 'gfx1010', 'gfx1030', 'gfx1031', 'gfx1032', 'gfx1033', 'gfx1034',
    'gfx1035', 'gfx1036', 'gfx1100', 'gfx1101', 'gfx1102', 'gfx1103', 'gfx1150', 'gfx1151'
]

remove_gcc_dependency_opts = {
    'LIBCXX_USE_COMPILER_RT': 'On',
    'LIBCXX_CXX_ABI': 'libcxxabi',
    'LIBCXX_DEFAULT_ABI_LIBRARY': 'libcxxabi',

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
    # Moved to general_opts for ease of building with openmp offload (or other multi-stage builds)
    # 'CLANG_DEFAULT_LINKER': 'lld',
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


@contextlib.contextmanager
def _wrap_env(path="", ld_path=""):
    """Wrap the environment with the path and ld_path."""
    orig_path = os.getenv('PATH', '')
    orig_ld_library_path = os.getenv('LD_LIBRARY_PATH', '')

    path = ':'.join(filter(None, [path, orig_path]))
    ld_path = ':'.join(filter(None, [ld_path, orig_ld_library_path]))

    setvar('PATH', path)
    setvar('LD_LIBRARY_PATH', ld_path)

    try:
        yield
    finally:
        setvar('PATH', orig_path)
        setvar('LD_LIBRARY_PATH', orig_ld_library_path)


class EB_LLVMcore(CMakeMake):
    """
    Support for building and installing LLVM
    """

    minimal_conflicts = [
        'bootstrap',
        'full_llvm',
        'python_bindings',
        'build_clang_extras',
        'build_bolt',
        'build_lld',
        'build_lldb',
        'build_runtimes',
        'build_openmp',
        'build_openmp_tools',
        'usepolly',
    ]

    @staticmethod
    def extra_options():
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'amd_gfx_list': [None, "List of AMDGPU targets to build for. Possible values: " +
                             ', '.join(AMDGPU_GFX_SUPPORT), CUSTOM],
            'assertions': [False, "Enable assertions.  Helps to catch bugs in Clang.", CUSTOM],
            'build_targets': [None, "Build targets for LLVM (host architecture if None). Possible values: " +
                                    ', '.join(ALL_TARGETS), CUSTOM],
            'bootstrap': [True, "Build LLVM-Clang using itself", CUSTOM],
            'full_llvm': [True, "Build LLVM without any dependency", CUSTOM],
            'minimal': [False, "Build LLVM only", CUSTOM],
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
            'build_openmp_tools': [True, "Build the LLVM OpenMP tools interface", CUSTOM],
            'usepolly': [False, "Build Clang with polly", CUSTOM],
            'disable_werror': [False, "Disable -Werror for all projects", CUSTOM],
            'test_suite_max_failed': [0, "Maximum number of failing tests (does not count allowed failures)", CUSTOM],
        })

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize LLVM-specific variables."""
        super(EB_LLVMcore, self).__init__(*args, **kwargs)

        # Allow running with older versions of LLVM for minimal builds in order to replace EB_LLVM easyblock
        if not self.cfg['minimal'] and LooseVersion(self.version) < LooseVersion('18.1.6'):
            raise EasyBuildError("LLVM version %s is not supported, please use version 18.1.6 or newer", self.version)

        self.llvm_src_dir = None
        self.llvm_obj_dir_stage1 = None
        self.llvm_obj_dir_stage2 = None
        self.llvm_obj_dir_stage3 = None
        self.intermediate_projects = ['llvm', 'clang']
        self.intermediate_runtimes = ['compiler-rt', 'libunwind', 'libcxx', 'libcxxabi']
        if not self.cfg['minimal']:
            self.final_projects = ['llvm', 'mlir', 'clang', 'flang']
        else:
            self.final_projects = ['llvm']
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
            general_opts['LIBCXX_ENABLE_STATIC_ABI_LIBRARY'] = 'ON'
            general_opts['LIBCXX_ENABLE_ABI_LINKER_SCRIPT'] = 'OFF'
            general_opts['LIBCXXABI_ENABLE_STATIC'] = 'ON'
            general_opts['LIBUNWIND_ENABLE_STATIC'] = 'ON'

        # RTTI
        if self.cfg["enable_rtti"]:
            general_opts['LLVM_REQUIRES_RTTI'] = 'ON'
            general_opts['LLVM_ENABLE_RTTI'] = 'ON'
            # Does not work with Flang
            # general_opts['LLVM_ENABLE_EH'] = 'ON'

        self.full_llvm = self.cfg['full_llvm']

        if self.cfg['minimal']:
            conflicts = [_ for _ in self.minimal_conflicts if self.cfg[_]]
            if conflicts:
                raise EasyBuildError("Minimal build conflicts with `%s`", ', '.join(conflicts))

        # Other custom options
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
        if self.cfg['build_openmp_tools']:
            if not self.cfg['build_openmp']:
                raise EasyBuildError("Building OpenMP tools requires building OpenMP runtime")
        if self.cfg['usepolly']:
            self.final_projects.append('polly')
        if self.cfg['build_clang_extras']:
            self.final_projects.append('clang-tools-extra')
        if self.cfg['build_lld']:
            self.intermediate_projects.append('lld')
            self.final_projects.append('lld')
            # This should be the default to make offload multi-stage compilations easier
            general_opts['CLANG_DEFAULT_LINKER'] = 'lld'
            general_opts['FLANG_DEFAULT_LINKER'] = 'lld'
        if self.cfg['build_lldb']:
            self.final_projects.append('lldb')
            if self.full_llvm:
                remove_gcc_dependency_opts['LLDB_ENABLE_LIBXML2'] = 'Off'
                remove_gcc_dependency_opts['LLDB_ENABLE_LZMA'] = 'Off'
                remove_gcc_dependency_opts['LLDB_ENABLE_PYTHON'] = 'Off'
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

        unknown_targets = set(build_targets) - set(ALL_TARGETS)

        if unknown_targets:
            raise EasyBuildError("Some of the chosen build targets (%s) are not in %s.",
                                 ', '.join(unknown_targets), ', '.join(ALL_TARGETS))
        exp_targets = set(build_targets) & set(LLVM_EXPERIMENTAL_TARGETS)
        if exp_targets:
            self.log.warning("Experimental targets %s are being used.", ', '.join(exp_targets))

        self.build_targets = build_targets or []

        self.nvptx_cond = 'NVPTX' in self.build_targets
        self.amd_cond = 'AMDGPU' in self.build_targets
        self.all_cond = 'all' in self.build_targets
        self.cuda_cc = []
        if self.nvptx_cond or self.all_cond:
            # list of CUDA compute capabilities to use can be specifed in two ways (where (2) overrules (1)):
            # (1) in the easyconfig file, via the custom cuda_compute_capabilities;
            # (2) in the EasyBuild configuration, via --cuda-compute-capabilities configuration option;
            ec_cuda_cc = self.cfg['cuda_compute_capabilities']
            cfg_cuda_cc = build_option('cuda_compute_capabilities')
            cuda_cc = cfg_cuda_cc or ec_cuda_cc or []
            if not cuda_cc and self.nvptx_cond:
                raise EasyBuildError(
                    "Can't build Clang with CUDA support without specifying 'cuda-compute-capabilities'"
                    )
            else:
                self.cuda_cc = [cc.replace('.', '') for cc in cuda_cc]

        self.amd_gfx = []
        if self.amd_cond or self.all_cond:
            self.amd_gfx = self.cfg['amd_gfx_list'] or []
            if not self.amd_gfx and self.amd_cond:
                raise EasyBuildError(
                    "Can't build Clang with AMDGPU support without specifying 'amd_gfx_list'"
                    )
            else:
                self.log.info("Using AMDGPU targets: %s", ', '.join(self.amd_gfx))

        general_opts['CMAKE_BUILD_TYPE'] = self.build_type
        general_opts['CMAKE_INSTALL_PREFIX'] = self.installdir
        if self.toolchain.options['pic']:
            general_opts['CMAKE_POSITION_INDEPENDENT_CODE'] = 'ON'

        general_opts['LLVM_TARGETS_TO_BUILD'] = '"%s"' % ';'.join(build_targets)

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
            self.log.info("Using %s as Z3 root", z3_root)
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
            self._cmakeopts['OPENMP_ENABLE_LIBOMPTARGET'] = 'ON'
            self._cmakeopts['LIBOMP_INSTALL_ALIASES'] = 'OFF'
            if not self.cfg['build_openmp_tools']:
                self._cmakeopts['OPENMP_ENABLE_OMPT_TOOLS'] = 'OFF'

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
        # Allow running with older versions of LLVM for minimal builds in order to replace EB_LLVM easyblock
        gcc_version = get_software_version('GCCcore')
        if not self.cfg['minimal'] and LooseVersion(gcc_version) < LooseVersion('13'):
            raise EasyBuildError("LLVM %s requires GCC 13 or newer, found %s", self.version, gcc_version)

        # Lit is needed for running tests-suite
        lit_root = get_software_root('lit')
        if not lit_root:
            if not self.cfg['skip_all_tests']:
                raise EasyBuildError("Can't find `lit`, needed for running tests-suite")

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

        # Libxml2
        xml2_root = get_software_root('libxml2')
        if xml2_root:
            if self.full_llvm:
                self.log.warning("LLVM is being built in `full_llvm` mode, libxml2 will not be used")
            else:
                general_opts['LLVM_ENABLE_LIBXML2'] = 'ON'
                # general_opts['LIBXML2_ROOT'] = xml2_root

        self.llvm_obj_dir_stage1 = os.path.join(self.builddir, 'llvm.obj.1')
        if self.cfg['bootstrap']:
            self._configure_intermediate_build()
            # if self.full_llvm:
            #     self.intermediate_projects.append('libc')
            #     self.final_projects.append('libc')
        else:
            self._configure_final_build()

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
        general_opts['GCC_INSTALL_PREFIX'] = gcc_prefix
        self.log.debug("Using %s as GCC_INSTALL_PREFIX", gcc_prefix)

        # If we don't want to build with CUDA (not in dependencies) trick CMakes FindCUDA module into not finding it by
        # using the environment variable which is used as-is and later checked for a falsy value when determining
        # whether CUDA was found
        if not get_software_root('CUDA'):
            setvar('CUDA_NVCC_EXECUTABLE', 'IGNORE')

        if 'openmp' in self.final_projects:
            gpu_archs = []
            gpu_archs += ['sm_%s' % cc for cc in self.cuda_cc]
            gpu_archs += self.amd_gfx
            if gpu_archs:
                general_opts['LIBOMPTARGET_DEVICE_ARCHITECTURES'] = '"%s"' % ';'.join(gpu_archs)

        self._configure_general_build()

        self.add_cmake_opts()
        super(EB_LLVMcore, self).configure_step(
            builddir=self.llvm_obj_dir_stage1,
            srcdir=os.path.join(self.llvm_src_dir, "llvm")
            )

    def disable_sanitizer_tests(self):
        """Disable the tests of all the sanitizers by removing the test directories from the build system"""
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

    def configure_step2(self):
        """Configure the second stage of the bootstrap."""
        self._cmakeopts = {}
        self._configure_general_build()
        self._configure_intermediate_build()
        if self.full_llvm:
            self._cmakeopts.update(remove_gcc_dependency_opts)

    def configure_step3(self):
        """Configure the third stage of the bootstrap."""
        self._cmakeopts = {}
        self._configure_general_build()
        self._configure_final_build()
        if self.full_llvm:
            self._cmakeopts.update(remove_gcc_dependency_opts)

    def build_with_prev_stage(self, prev_dir, stage_dir):
        """Build LLVM using the previous stage."""
        curdir = os.getcwd()

        bin_dir = os.path.join(prev_dir, 'bin')
        lib_dir_runtime = self.get_runtime_lib_path(prev_dir, fail_ok=False)

        # Give priority to the libraries in the current stage if compiled to avoid failures due to undefined symbols
        # e.g. when calling the compiled clang-ast-dump for stage 3
        lib_path = ':'.join(filter(None, [
            os.path.join(stage_dir, lib_dir_runtime),
            os.path.join(prev_dir, lib_dir_runtime),
        ]))

        # Needed for passing the variables to the build command
        with _wrap_env(bin_dir, lib_path):
            # If building with rpath, create RPATH wrappers for the Clang compilers for stage 2 and 3
            if build_option('rpath'):
                # !!! Should be replaced with ClangFlang (or correct naming) toolchain once available
                #     as this will only create rpath wrappers for Clang and not Flang
                my_toolchain = Clang(name='Clang', version='1')
                my_toolchain.prepare_rpath_wrappers(
                    rpath_include_dirs=[
                        os.path.join(self.installdir, 'lib'),
                        os.path.join(self.installdir, 'lib64'),
                        os.path.join(self.installdir, lib_dir_runtime),
                        ]
                    )
                self.log.info("Prepared rpath wrappers")

                # add symlink for 'opt' to wrapper dir, since Clang expects it in the same directory
                # see https://github.com/easybuilders/easybuild-easyblocks/issues/3075
                clang_wrapper_dir = os.path.dirname(which('clang'))
                symlink(os.path.join(prev_dir, 'opt'), os.path.join(clang_wrapper_dir, 'opt'))

                # RPATH wrappers add -Wl,rpath arguments to all command lines, including when it is just compiling
                # Clang by default warns about that, and then some configure tests use -Werror which turns those
                # warnings into errors. As a result, those configure tests fail, even though the compiler supports the
                # requested functionality (e.g. the test that checks if -fPIC is supported would fail, and it compiles
                # without resulting in relocation errors).
                # See https://github.com/easybuilders/easybuild-easyblocks/pull/2799#issuecomment-1270621100
                # Here, we add -Wno-unused-command-line-argument to CXXFLAGS to avoid these warnings alltogether
                cflags = os.getenv('CFLAGS', '')
                cxxflags = os.getenv('CXXFLAGS', '')
                setvar('CFLAGS', "%s %s" % (cflags, '-Wno-unused-command-line-argument'))
                setvar('CXXFLAGS', "%s %s" % (cxxflags, '-Wno-unused-command-line-argument'))

            # determine full path to clang/clang++ (which may be wrapper scripts in case of RPATH linking)
            clang = which('clang')
            clangxx = which('clang++')

            self._cmakeopts['CMAKE_C_COMPILER'] = clang
            self._cmakeopts['CMAKE_CXX_COMPILER'] = clangxx
            self._cmakeopts['CMAKE_ASM_COMPILER'] = clang
            self._cmakeopts['CMAKE_ASM_COMPILER_ID'] = 'Clang'

            self.add_cmake_opts()

            change_dir(stage_dir)
            self.log.debug("Configuring %s", stage_dir)
            cmd = "cmake %s %s" % (self.cfg['configopts'], os.path.join(self.llvm_src_dir, 'llvm'))
            run_cmd(cmd, log_all=True)

            self.log.debug("Building %s", stage_dir)
            cmd = "make %s VERBOSE=1" % self.make_parallel_opts
            run_cmd(cmd, log_all=True)

        change_dir(curdir)

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

    def _para_test_step(self, parallel=1):
        """Run test suite with the specified number of parallel jobs for make."""
        basedir = self.final_dir

        change_dir(basedir)
        lib_path = ''
        if self.cfg['build_runtimes']:
            lib_dir_runtime = self.get_runtime_lib_path(basedir, fail_ok=False)
            lib_path = os.path.join(basedir, lib_dir_runtime)
        with _wrap_env(os.path.join(basedir, 'bin'), lib_path):
            cmd = "make -j %s check-all" % parallel
            (out, _) = run_cmd(cmd, log_all=False, log_ok=False, simple=False, regexp=False)
            self.log.debug(out)

        rgx_failed = re.compile(r'^ +Failed +: +([0-9]+)', flags=re.MULTILINE)
        mch = rgx_failed.search(out)
        if mch is None:
            rgx_passed = re.compile(r'^ +Passed +: +([0-9]+)', flags=re.MULTILINE)
            mch = rgx_passed.search(out)
            if mch is None:
                self.log.warning("Failed to extract number of failed/passed test results from output")
                num_failed = None
            else:
                num_failed = 0
        else:
            num_failed = int(mch.group(1))

        return num_failed

    def test_step(self):
        """Run tests on final stage (unless disabled)."""
        if not self.cfg['skip_all_tests']:
            max_failed = self.cfg['test_suite_max_failed']
            self.log.info("Running test-suite with parallel jobs")
            num_failed = self._para_test_step(parallel=self.cfg['parallel'])
            if num_failed is None:
                self.log.warning("Tests with parallel jobs failed, retrying with single job")
                num_failed = self._para_test_step(parallel=1)
            if num_failed is None:
                raise EasyBuildError("Failed to extract test results from output")

            if num_failed > max_failed:
                raise EasyBuildError("Too many failed tests: %s (%s allowed)", num_failed, max_failed)

            self.log.info("Test-suite completed with %s failed tests (%s allowed)", num_failed, max_failed)

    def install_step(self):
        """Install stage 1 or 3 (if bootstrap) binaries."""
        basedir = self.final_dir
        change_dir(basedir)

        if self.cfg['build_runtimes']:
            orig_ld_library_path = os.getenv('LD_LIBRARY_PATH')
            lib_dir_runtime = self.get_runtime_lib_path(basedir, fail_ok=False)

            lib_path = ':'.join([
                os.path.join(basedir, lib_dir_runtime),
                orig_ld_library_path
            ])

            # _preinstallopts = self.cfg.get('preinstallopts', '')
            self.cfg.update('preinstallopts', ' '.join([
                'LD_LIBRARY_PATH=%s' % lib_path
            ]))

        super(EB_LLVMcore, self).install_step()

    def post_install_step(self):
        """Install python bindings."""
        super(EB_LLVMcore, self).post_install_step()

        # copy Python bindings here in post-install step so that it is not done more than once in multi_deps context
        if self.cfg['python_bindings']:
            python_bindings_source_dir = os.path.join(self.llvm_src_dir, "clang", "bindings", "python")
            python_bindins_target_dir = os.path.join(self.installdir, 'lib', 'python')
            shutil.copytree(python_bindings_source_dir, python_bindins_target_dir)

            python_bindings_source_dir = os.path.join(self.llvm_src_dir, "mlir", "python")
            shutil.copytree(python_bindings_source_dir, python_bindins_target_dir, dirs_exist_ok=True)

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

    def banned_linked_shared_libs(self):
        """Return a list of shared libraries that should not be linked against."""
        res = []
        if self.full_llvm:
            self.log.info("Checking that no GCC shared libraries are linked against")
            res += ['libstdc++', 'libgcc_s', 'libicuuc']
        if not self.build_shared:
            # Libraries should be linked statically
            self.log.info("Checking that no shared libraries are linked against in static build")
            res += ['libc++', 'libc++abi', 'libunwind']
        return res

    def sanity_check_step(self, custom_paths=None, custom_commands=None, extension=False, extra_modules=None):
        """Perform sanity checks on the installed LLVM."""
        if self.cfg['build_runtimes']:
            lib_dir_runtime = self.get_runtime_lib_path(self.installdir, fail_ok=False)
        shlib_ext = '.' + get_shared_lib_ext()

        resdir_version = self.version.split('.')[0]

        # Detect OpenMP support for CPU architecture
        arch = get_cpu_architecture()
        # Check architecture explicitly since Clang uses potentially different names
        if arch == X86_64:
            arch = 'x86_64'
        elif arch == POWER:
            arch = 'ppc64'
        elif arch == AARCH64:
            arch = 'aarch64'

        check_files = []
        check_bin_files = []
        check_lib_files = []
        check_inc_files = []
        check_dirs = ['include/llvm', 'include/llvm-c', 'lib/cmake/llvm']
        custom_commands = [
            'llvm-ar --help', 'llvm-ranlib --help', 'llvm-nm --help', 'llvm-objdump --help',
        ]

        if self.build_shared:
            check_lib_files += ['libLLVM.so']

        if 'clang' in self.final_projects:
            check_bin_files += [
                'clang', 'clang++', 'clang-cpp', 'clang-cl', 'clang-repl', 'hmaptool', 'amdgpu-arch', 'nvptx-arch',
                'intercept-build', 'scan-build', 'scan-build-py', 'scan-view', 'analyze-build', 'c-index-test',
                'clang-tblgen',
            ]
            check_lib_files += [
                'libclang.so', 'libclang-cpp.so', 'libclangAST.a', 'libclangCrossTU.a', 'libclangFrontend.a',
                'libclangInterpreter.a', 'libclangParse.a', 'libclangTooling.a'
            ]
            check_dirs += [
                'lib/cmake/clang', 'include/clang'
            ]
            custom_commands += [ 'llvm-config --cxxflags', 'clang --help', 'clang++ --help']

        if 'clang-tools-extra' in self.final_projects:
            check_bin_files += [
                'clangd', 'clang-tidy', 'clang-pseudo', 'clang-include-fixer', 'clang-query', 'clang-move',
                'clang-reorder-fields', 'clang-include-cleaner', 'clang-apply-replacements',
                'clang-change-namespace', 'pp-trace', 'modularize'
            ]
            check_lib_files += [
                'libclangTidy.a', 'libclangQuery.a', 'libclangIncludeFixer.a', 'libclangIncludeCleaner.a',
            ]
            check_dirs += ['include/clang-tidy']
        if 'flang' in self.final_projects:
            check_bin_files += ['bbc', 'flang-new', 'flang-to-external-fc', 'f18-parse-demo', 'fir-opt', 'tco']
            check_lib_files += [
                'libFortranRuntime.a', 'libFortranSemantics.a', 'libFortranLower.a', 'libFortranParser.a',
                'libFIRCodeGen.a', 'libflangFrontend.a', 'libFortranCommon.a', 'libFortranDecimal.a',
                'libHLFIRDialect.a'
            ]
            check_dirs += ['lib/cmake/flang', 'include/flang']
            custom_commands += ['bbc --help', 'mlir-tblgen --help', 'flang-new --help']
        if 'lld' in self.final_projects:
            check_bin_files += ['ld.lld', 'lld', 'lld-link', 'wasm-ld']
            check_lib_files += [
                'liblldCOFF.a', 'liblldCommon.a', 'liblldELF.a', 'liblldMachO.a', 'liblldMinGW.a', 'liblldWasm.a'
            ]
            check_dirs += ['lib/cmake/lld', 'include/lld']
        if 'lldb' in self.final_projects:
            check_bin_files += ['lldb']
            if self.build_shared:
                check_lib_files += ['liblldb.so']
            check_dirs += ['include/lldb']
        if 'mlir' in self.final_projects:
            check_bin_files += ['mlir-opt', 'tblgen-to-irdl', 'mlir-pdll']
            check_lib_files += [
                'libMLIRIR.a', 'libmlir_async_runtime.so', 'libmlir_arm_runner_utils.so', 'libmlir_c_runner_utils.so',
                'libmlir_float16_utils.so'
            ]
            check_dirs += ['lib/cmake/mlir', 'include/mlir', 'include/mlir-c']
        # if 'compiler-rt' in self.final_runtimes:
        #     pth = os.path.join('lib', 'clang', resdir_version, lib_dir_runtime)
        #     check_files += [os.path.join(pth, _) for _ in [
        #         # This should probably be more finetuned depending on what features of compiler-rt are used
        #         'libclang_rt.xray.a', 'libclang_rt.fuzzer.a', 'libclang_rt.gwp_asan.a', 'libclang_rt.profile.a',
        #         'libclang_rt.lsan.a', 'libclang_rt.asan.a', 'libclang_rt.hwasan.a'
        #     ]]
        #     check_dirs += ['include/sanitizer', 'include/fuzzer', 'include/orc', 'include/xray']
        if 'libunwind' in self.final_runtimes:
            check_files += [os.path.join(lib_dir_runtime, _) for _ in ['libunwind.a']]
            if self.build_shared:
                check_files += [os.path.join(lib_dir_runtime, _) for _ in ['libunwind.so']]
            check_inc_files += ['unwind.h', 'libunwind.h', 'mach-o/compact_unwind_encoding.h']
        if 'libcxx' in self.final_runtimes:
            check_files += [os.path.join(lib_dir_runtime, _) for _ in ['libc++.a']]
            if self.build_shared:
                check_files += [os.path.join(lib_dir_runtime, _) for _ in ['libc++.so']]
            check_dirs += ['include/c++/v1']
        if 'libcxxabi' in self.final_runtimes:
            check_files += [os.path.join(lib_dir_runtime, _) for _ in ['libc++abi.a']]
            if self.build_shared:
                check_files += [os.path.join(lib_dir_runtime, _) for _ in ['libc++abi.so']]

        if 'polly' in self.final_projects:
            check_lib_files += ['libPolly.a', 'libPollyISL.a']
            if self.build_shared:
                check_lib_files += ['libPolly.so']
            check_dirs += ['lib/cmake/polly', 'include/polly']
            custom_commands += [
                ' | '.join([
                    'echo \'int main(int argc, char **argv) { return 0; }\'',
                    'clang -xc -O3 -mllvm -polly -'
                ]) + ' && ./a.out && rm -f a.out'
            ]
        if 'bolt' in self.final_projects:
            check_bin_files += ['llvm-bolt', 'llvm-boltdiff', 'llvm-bolt-heatmap']
            check_lib_files += ['libbolt_rt_instr.a']
        if 'openmp' in self.final_projects:
            check_lib_files += ['libomp.so', 'libompd.so']
            check_lib_files += ['libomptarget.so', 'libomptarget.rtl.%s.so' % arch]
            if 'NVPTX' in self.cfg['build_targets']:
                check_lib_files += ['libomptarget.rtl.cuda.so']
                check_lib_files += ['libomptarget-nvptx-sm_%s.bc' % cc for cc in self.cuda_cc]
            if 'AMDGPU' in self.cfg['build_targets']:
                check_lib_files += ['libomptarget.rtl.amdgpu.so']
                check_lib_files += ['llibomptarget-amdgpu-%s.bc' % gfx for gfx in self.amd_gfx]
        if self.cfg['build_openmp_tools']:
            check_files += [os.path.join('lib', 'clang', resdir_version, 'include', 'ompt.h')]
        if self.cfg['python_bindings']:
            custom_commands += ["python -c 'import clang'"]
            custom_commands += ["python -c 'import mlir'"]

        for libso in filter(lambda x: x.endswith('.so'), check_lib_files):
            libext = libso.replace('.so', shlib_ext)
            if libext not in check_lib_files:
                check_lib_files.append(libext)
            check_lib_files.remove(libso)

        check_files += [os.path.join('bin', _) for _ in check_bin_files]
        check_files += [os.path.join('lib', _) for _ in check_lib_files]
        check_files += [os.path.join('include', _) for _ in check_inc_files]

        custom_paths = {
            'files': check_files,
            'dirs': check_dirs,
        }

        return super(EB_LLVMcore, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

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
        libs = ['lib', 'lib64']
        if self.cfg['build_runtimes']:
            runtime_lib_path = self.get_runtime_lib_path(self.installdir, fail_ok=False)
            libs.append(runtime_lib_path)
        guesses = super(EB_LLVMcore, self).make_module_req_guess()
        guesses.update({
            'CPATH': [],
            'LIBRARY_PATH': libs,
            'LD_LIBRARY_PATH': libs,
        })
        return guesses
