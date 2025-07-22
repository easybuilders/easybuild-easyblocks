##
# Copyright 2020-2025 Ghent University
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
import stat

from easybuild.framework.easyconfig import CUSTOM
from easybuild.toolchains.compiler.clang import Clang
from easybuild.tools import LooseVersion
from easybuild.tools.utilities import trace_msg
from easybuild.tools.build_log import EasyBuildError, print_msg, print_warning
from easybuild.tools.config import ERROR, IGNORE, SEARCH_PATH_LIB_DIRS, build_option
from easybuild.tools.environment import setvar
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, copy_dir, adjust_permissions
from easybuild.tools.filetools import mkdir, remove_file, symlink, which, write_file, remove_dir
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS, get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd, EasyBuildExit
from easybuild.tools.systemtools import AARCH32, AARCH64, POWER, RISCV64, X86_64, POWER_LE
from easybuild.tools.systemtools import get_cpu_architecture, get_cpu_family, get_shared_lib_ext

from easybuild.easyblocks.generic.cmakemake import CMakeMake, get_cmake_python_config_dict

BUILD_TARGET_AMDGPU = 'AMDGPU'
BUILD_TARGET_NVPTX = 'NVPTX'

LLVM_TARGETS = [
    'AArch64', BUILD_TARGET_AMDGPU, 'ARM', 'AVR', 'BPF', 'Hexagon', 'Lanai', 'LoongArch', 'Mips', 'MSP430',
    BUILD_TARGET_NVPTX, 'PowerPC', 'RISCV', 'Sparc', 'SPIRV', 'SystemZ', 'VE', 'WebAssembly', 'X86', 'XCore',
    'all'
]
LLVM_EXPERIMENTAL_TARGETS = [
    'ARC', 'CSKY', 'DirectX', 'M68k', 'Xtensa',
]
ALL_TARGETS = LLVM_TARGETS + LLVM_EXPERIMENTAL_TARGETS

DEFAULT_TARGETS_MAP = {
    AARCH32: ['ARM'],
    AARCH64: ['AArch64'],
    POWER: ['PowerPC'],
    RISCV64: ['RISCV'],
    X86_64: ['X86'],
}

AVAILABLE_OFFLOAD_DLOPEN_PLUGIN_OPTIONS = [
    'cuda',
    'amdgpu'
]

# Used for full_llvm=True to remove any dependency on GCC/GCCcore
GCC_DEPENDENCY_OPTS_DEFAULT = {
    'CLANG_DEFAULT_CXX_STDLIB': 'libc++',
    'CLANG_DEFAULT_RTLIB': 'compiler-rt',
    'CLANG_DEFAULT_UNWINDLIB': 'libunwind',

    'COMPILER_RT_BUILD_GWP_ASAN': 'OFF',
    'COMPILER_RT_ENABLE_INTERNAL_SYMBOLIZER': 'ON',
    'COMPILER_RT_ENABLE_STATIC_UNWINDER': 'ON',  # https://lists.llvm.org/pipermail/llvm-bugs/2016-July/048424.html
    'COMPILER_RT_USE_BUILTINS_LIBRARY': 'ON',
    'COMPILER_RT_USE_LIBCXX': 'ON',
    'COMPILER_RT_USE_LLVM_UNWINDER': 'ON',

    'LIBCXX_CXX_ABI': 'libcxxabi',
    'LIBCXX_DEFAULT_ABI_LIBRARY': 'libcxxabi',
    # Needed as libatomic could not be present on the system (compilation and tests will succeed because of
    # a possible GCCcore builddep, but usage/sanity check will fail due to missing libatomic)
    'LIBCXX_HAS_ATOMIC_LIB': 'OFF',
    'LIBCXX_HAS_GCC_S_LIB': 'OFF',
    'LIBCXX_USE_COMPILER_RT': 'ON',

    'LIBCXXABI_HAS_GCC_S_LIB': 'OFF',
    'LIBCXXABI_USE_LLVM_UNWINDER': 'ON',
    'LIBCXXABI_USE_COMPILER_RT': 'ON',

    'LIBUNWIND_HAS_GCC_S_LIB': 'OFF',
    'LIBUNWIND_USE_COMPILER_RT': 'ON',

    'SANITIZER_USE_STATIC_LLVM_UNWINDER': 'ON',
}

DISABLE_WERROR_OPTS = {
    'BENCHMARK_ENABLE_WERROR': 'OFF',
    'COMPILER_RT_ENABLE_WERROR': 'OFF',
    'FLANG_ENABLE_WERROR': 'OFF',
    'LIBC_WNO_ERROR': 'ON',
    'LIBCXX_ENABLE_WERROR': 'OFF',
    'LIBUNWIND_ENABLE_WERROR': 'OFF',
    'LLVM_ENABLE_WERROR': 'OFF',
    'OPENMP_ENABLE_WERROR': 'OFF',
}

GENERAL_OPTS = {
    'CMAKE_VERBOSE_MAKEFILE': 'ON',
    'LLVM_INCLUDE_BENCHMARKS': 'OFF',
    'LLVM_INSTALL_UTILS': 'ON',
    # If EB is launched from a venv, avoid giving priority to the venv's python
    'Python3_FIND_VIRTUALENV': 'STANDARD',
}


@contextlib.contextmanager
def _wrap_env(path="", ld_path=""):
    """Wrap the environment with $PATH and $LD_LIBRARY_PATH."""
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


def get_arch_prefix():
    """Return the architecture prefix"""
    arch = get_cpu_architecture()
    if arch == POWER:
        if get_cpu_family() == POWER_LE:
            return 'powerpc64le'
        else:
            return 'powerpc64'
    else:
        return arch.lower()


class EB_LLVM(CMakeMake):
    """
    Support for building and installing LLVM
    """

    minimal_conflicts = [
        'build_bolt',
        'build_clang_extras',
        'build_lld',
        'build_lldb',
        'build_openmp',
        'build_openmp_tools',
        'build_runtimes',
        'bootstrap',
        'full_llvm',
        'python_bindings',
        'use_polly',
    ]

    # Create symlink between equivalent host triples, useful so that other build processes that relies on older
    # triple names can still work when passing the old name to --target
    symlink_lst = [
        ('x86_64-unknown-linux-gnu', 'x86_64-pc-linux'),
        ('x86_64-unknown-linux-gnu', 'x86_64-pc-linux-gnu'),
    ]

    # From LLVM 19, GCC_INSTALL_PREFIX is not supported anymore to hardcode the GCC installation path into the binaries;
    # Now every compilers needs a .cfg file with the --gcc-install-dir option
    # This list tells which compilers need to have a .cfg file created
    # NOTE: flang is the expected name also for the 'flang-new' compiler
    cfg_compilers = ['clang', 'clang++', 'flang']

    @staticmethod
    def extra_options():
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'amd_gfx_list': [None, "List of AMDGPU targets to build for.", CUSTOM],
            'assertions': [False, "Enable assertions.  Helps to catch bugs in Clang.", CUSTOM],
            'bootstrap': [True, "Build LLVM-Clang using itself", CUSTOM],
            'build_bolt': [False, "Build the LLVM bolt binary optimizer", CUSTOM],
            'build_clang_extras': [False, "Build the LLVM Clang extra tools", CUSTOM],
            'build_lld': [False, "Build the LLVM lld linker", CUSTOM],
            'build_lldb': [False, "Build the LLVM lldb debugger", CUSTOM],
            'build_openmp': [True, "Build the LLVM OpenMP runtime", CUSTOM],
            'build_openmp_library_aliases': [False, "Install symlinks to libomp (e.g. libgomp, libiomp5)", CUSTOM],
            'build_openmp_offload': [True, "Build the LLVM OpenMP offload runtime", CUSTOM],
            'build_openmp_tools': [True, "Build the LLVM OpenMP tools interface", CUSTOM],
            'build_runtimes': [False, "Build the LLVM runtimes (compiler-rt, libunwind, libcxx, libcxxabi)", CUSTOM],
            'build_targets': [None, "Build targets for LLVM (host architecture if None). Possible values: " +
                                    ', '.join(ALL_TARGETS), CUSTOM],
            'debug_tests': [True, "Enable verbose output for tests", CUSTOM],
            'disable_werror': [False, "Disable -Werror for all projects", CUSTOM],
            'enable_rtti': [True, "Enable RTTI", CUSTOM],
            'full_llvm': [False, "Build LLVM without any dependency", CUSTOM],
            'minimal': [False, "Build LLVM only", CUSTOM],
            'python_bindings': [False, "Install python bindings", CUSTOM],
            'skip_all_tests': [False, "Skip running of tests", CUSTOM],
            'skip_sanitizer_tests': [True, "Do not run the sanitizer tests", CUSTOM],
            'test_suite_ignore_patterns': [None, "List of test to ignore (if the string matches)", CUSTOM],
            'test_suite_max_failed': [0, "Maximum number of failing tests (does not count allowed failures)", CUSTOM],
            'test_suite_timeout_single': [None, "Timeout for each individual test in the test suite", CUSTOM],
            'test_suite_timeout_total': [None, "Timeout for total running time of the testsuite", CUSTOM],
            'use_pic': [True, "Build with Position Independent Code (PIC)", CUSTOM],
            'usepolly': [None, "DEPRECATED, alias for 'use_polly'", CUSTOM],
            'use_polly': [None, "Build Clang with polly, disabled by default", CUSTOM],
        })

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize LLVM-specific variables."""
        super().__init__(*args, **kwargs)

        if self.cfg['usepolly'] is not None:
            self.log.deprecated("Use of easyconfig parameter 'usepolly', replace by 'use_polly'", '6.0')
            if self.cfg['use_polly'] is None:
                self.cfg['use_polly'] = self.cfg['usepolly']
            else:
                # Do not overwrite value set via the new name
                print_warning("Both 'usepolly' and 'use_polly' are set, please use only 'use_polly'")

        self.llvm_obj_dir_stage1 = None
        self.llvm_obj_dir_stage2 = None
        self.llvm_obj_dir_stage3 = None
        self.intermediate_projects = ['llvm', 'clang']
        self.intermediate_runtimes = ['compiler-rt', 'libunwind', 'libcxx', 'libcxxabi']
        if self.cfg['minimal']:
            self.final_projects = ['llvm']
        else:
            self.final_projects = ['llvm', 'mlir', 'clang', 'flang']
            # Bypass the .mod file check for GCCcore installs
            self.cfg['skip_mod_files_sanity_check'] = True
        self.final_runtimes = []
        self._gcc_prefix = None
        self._gcc_root = None
        self.runtimes_cmake_args = {
            'CMAKE_C_COMPILER': [],
            'CMAKE_C_FLAGS': [],
            'CMAKE_CXX_COMPILER': [],
            'CMAKE_CXX_FLAGS': [],
            'CMAKE_EXE_LINKER_FLAGS': [],
            }
        self.offload_targets = ['host']
        self.host_triple = None
        self.dynamic_linker = None

        # Shared
        off_opts, on_opts = [], []
        self.build_shared = self.cfg.get('build_shared_libs', False)
        if self.build_shared:
            self.cfg['build_shared_libs'] = None
            on_opts.extend(['LLVM_BUILD_LLVM_DYLIB', 'LLVM_LINK_LLVM_DYLIB', 'LIBCXX_ENABLE_SHARED',
                            'LIBCXXABI_ENABLE_SHARED', 'LIBUNWIND_ENABLE_SHARED'])
        else:
            off_opts.extend(['LIBCXX_ENABLE_ABI_LINKER_SCRIPT', 'LIBCXX_ENABLE_SHARED', 'LIBCXXABI_ENABLE_SHARED',
                             'LIBUNWIND_ENABLE_SHARED', 'LLVM_BUILD_LLVM_DYLIB', 'LLVM_LINK_LLVM_DYLIB'])
            on_opts.extend(['LIBCXX_ENABLE_STATIC', 'LIBCXX_ENABLE_STATIC_ABI_LIBRARY', 'LIBCXXABI_ENABLE_STATIC',
                            'LIBUNWIND_ENABLE_STATIC'])

        # RTTI
        if self.cfg['enable_rtti']:
            on_opts.extend(['LLVM_ENABLE_RTTI', 'LLVM_REQUIRES_RTTI'])
            # Does not work yet with Flang
            # on_opts.append('LLVM_ENABLE_EH')

        if self.cfg['use_pic']:
            on_opts.append('CMAKE_POSITION_INDEPENDENT_CODE')

        # General options being passed to every build stage.
        # Here, options that will be required in all build stages should be added.
        # Update _cmakeopts in _configure_{general,intermediate,final}_build if
        # build option is only relevant for a single build step.
        self.general_opts = GENERAL_OPTS.copy()

        for opt in on_opts:
            self.general_opts[opt] = 'ON'

        for opt in off_opts:
            self.general_opts[opt] = 'OFF'

        self.full_llvm = self.cfg['full_llvm']

        if self.cfg['minimal']:
            conflicts = [_ for _ in self.minimal_conflicts if self.cfg[_]]
            if conflicts:
                raise EasyBuildError("Minimal build conflicts with '%s'", ', '.join(conflicts))

        # Other custom options
        if self.full_llvm:
            if not self.cfg['bootstrap']:
                raise EasyBuildError("Full LLVM build requires bootstrap build")
            if not self.cfg['build_lld']:
                raise EasyBuildError("Full LLVM build requires building lld")
            if not self.cfg['build_runtimes']:
                raise EasyBuildError("Full LLVM build requires building runtimes")
            self.log.info("Building LLVM without any GCC dependency")

        if self.cfg['disable_werror']:
            self.general_opts.update(DISABLE_WERROR_OPTS)

        if self.cfg['build_runtimes']:
            self.final_runtimes += ['compiler-rt', 'libunwind', 'libcxx', 'libcxxabi']

        if self.cfg['build_openmp']:
            self.final_projects.append('openmp')
        else:
            errors = []
            # check for all options that depend on OpenMP being enabled
            if self.cfg['build_openmp_tools']:
                errors.append("Building OpenMP tools requires building OpenMP runtime")

            if self.cfg['build_openmp_offload']:
                errors.append("Building OpenMP offload requires building OpenMP runtime")

            if self.cfg['build_openmp_library_aliases']:
                errors.append("Installing OpenMP library aliases requires building OpenMP runtime")

            if errors:
                raise EasyBuildError('\n'.join(errors), exit_code=EasyBuildExit.EASYCONFIG_ERROR)

        if self.cfg['build_openmp_offload']:
            # LLVM 19 added a new runtime target for explicit offloading
            # https://discourse.llvm.org/t/llvm-19-1-0-no-library-libomptarget-nvptx-sm-80-bc-found/81343
            if LooseVersion(self.version) >= '19':
                self.log.debug("Explicitly enabling OpenMP offloading for LLVM >= 19")
                self.final_runtimes.append('offload')
            else:
                self.log.debug("OpenMP offloading is included with the OpenMP runtime for LLVM < 19")

        if self.cfg['use_polly']:
            self.final_projects.append('polly')

        if self.cfg['build_clang_extras']:
            self.final_projects.append('clang-tools-extra')

        if self.cfg['build_lld']:
            self.intermediate_projects.append('lld')
            self.final_projects.append('lld')
            # This should be the default to make offload multi-stage compilations easier
            self.general_opts['CLANG_DEFAULT_LINKER'] = 'lld'
            self.general_opts['FLANG_DEFAULT_LINKER'] = 'lld'

        # Used for full_llvm=True to remove any dependency on GCC/GCCcore
        self.remove_gcc_dependency_opts = GCC_DEPENDENCY_OPTS_DEFAULT.copy()
        if self.cfg['build_lldb']:
            self.final_projects.append('lldb')
            self.remove_gcc_dependency_opts.update({
                'LLDB_ENABLE_LIBXML2': 'OFF',
                'LLDB_ENABLE_LZMA': 'OFF',
                'LLDB_ENABLE_PYTHON': 'OFF',
            })

        if self.cfg['build_bolt']:
            self.final_projects.append('bolt')

        # Fix for https://github.com/easybuilders/easybuild-easyblocks/issues/3689
        if LooseVersion(self.version) < '16':
            self.general_opts['LLVM_INCLUDE_GO_TESTS'] = 'OFF'

        self.log.info("Final projects to build: %s", ', '.join(self.final_projects))
        self.log.info("Final runtimes to build: %s", ', '.join(self.final_runtimes))

        # CMake options passed to each build stage.
        # Will be cleared between stages. If arguments are needed in multiple stages,
        # consider adding them to general_opts instead.
        self._cmakeopts = {}
        self._cfgopts = list(filter(None, self.cfg.get('configopts', '').split()))

    @property
    def gcc_prefix(self):
        """Return the GCC prefix (versioned folder in <gcc_root>/lib)."""
        self._set_gcc_prefix_probs()
        return self._gcc_prefix

    @property
    def gcc_root(self):
        """Return the GCC root folder from dependencies/toolchain."""
        self._set_gcc_prefix_probs()
        return self._gcc_root

    def _set_gcc_prefix_probs(self):
        """Set properties of currently loaded GCC installation"""
        if self._gcc_root is None:
            self._gcc_root, self._gcc_prefix = self._get_gcc_prefix()
            self.log.debug("Using %s as the gcc install location", self._gcc_prefix)

    @property
    def llvm_src_dir(self):
        """Return root source directory of LLVM (containing all components)"""
        # LLVM is the first source so we already have this in start_dir. Might be changed later
        return self.start_dir

    def _configure_build_targets(self):
        cuda_cc_list = self.cfg.get_cuda_cc_template_value("cuda_cc_space_sep", required=False).split()
        cuda_toolchain = hasattr(self.toolchain, 'COMPILER_CUDA_FAMILY')
        amd_gfx_list = self.cfg['amd_gfx_list'] or []

        # List of (lower-case) dependencies
        self.deps = [dep['name'].lower() for dep in self.cfg.dependencies()]

        # Build targets
        build_targets = self.cfg['build_targets'] or []
        if not build_targets:
            self.log.debug("No build targets specified, using default detection")
            arch = get_cpu_architecture()
            if arch not in DEFAULT_TARGETS_MAP:
                raise EasyBuildError("No default build targets defined for CPU architecture %s.", arch)
            build_targets += DEFAULT_TARGETS_MAP[arch]

            # If CUDA is included as a dep, add NVPTX as a target
            # There are (old) toolchains with CUDA as part of the toolchain
            if 'cuda' in self.deps or cuda_toolchain:
                self.log.info("CUDA dependency detected, adding NVPTX as a target")
                build_targets.append(BUILD_TARGET_NVPTX)
            elif cuda_cc_list:
                self.log.info("CUDA compute capabilities specified, adding NVPTX as a target")
                build_targets.append(BUILD_TARGET_NVPTX)

            # For AMDGPU support during runtime we need ROCR-Runtime and ROCT-Thunk-Interface. While split into
            # separate packages pre ROCm 6.2, it is now combined into ROCR-Runtime. As ROCR-Thunk-Interface was a
            # dependency for ROCR-Runtime before, checking for ROCR-Runtime as a dependency is sufficient.
            # Generally, ROCR-Runtime is not a hard dependency for LLVM. If not found, LLVM can still build
            # an offload-capable compiler runtime, and will try to dlopen the required libraries at runtime.
            # Therefore, also allow the build without ROCR-Runtime, with only the desired architecture list being set.
            # https://openmp.llvm.org/SupportAndFAQ.html#q-how-to-build-an-openmp-amdgpu-offload-capable-compiler
            if 'rocr-runtime' in self.deps:
                self.log.info("ROCR-Runtime dependency detected, adding AMDGPU as a target")
                build_targets.append(BUILD_TARGET_AMDGPU)
            elif amd_gfx_list:
                self.log.info("AMD GPU list specified, adding AMDGPU as a target")
                build_targets.append(BUILD_TARGET_AMDGPU)

            self.cfg['build_targets'] = build_targets
            self.log.debug("Using %s as default build targets for CPU architecture %s.", build_targets, arch)

        unknown_targets = set(build_targets) - set(ALL_TARGETS)

        if unknown_targets:
            raise EasyBuildError("Some of the chosen build targets (%s) are not in %s.",
                                 ', '.join(unknown_targets), ', '.join(ALL_TARGETS))
        exp_targets = set(build_targets) & set(LLVM_EXPERIMENTAL_TARGETS)
        if exp_targets:
            self.log.warning("Experimental targets %s are being used.", ', '.join(exp_targets))

        all_target_cond = 'all' in build_targets
        self.nvptx_target_cond = (BUILD_TARGET_NVPTX in build_targets) or all_target_cond
        self.amdgpu_target_cond = (BUILD_TARGET_AMDGPU in build_targets) or all_target_cond

        if ('cuda' in self.deps or cuda_toolchain) and not self.nvptx_target_cond:
            raise EasyBuildError("CUDA dependency detected, but NVPTX not in manually specified build targets")
        if cuda_cc_list and not self.nvptx_target_cond:
            raise EasyBuildError(
                "CUDA compute capabilities specified, but NVPTX not in manually specified build targets"
            )
        if 'rocr-runtime' in self.deps and not self.amdgpu_target_cond:
            raise EasyBuildError(
                "ROCR-Runtime dependency detected, but AMDGPU not in manually specified build targets"
            )
        if amd_gfx_list and not self.amdgpu_target_cond:
            raise EasyBuildError("AMD GPU list specified, but AMDGPU not in manually specified build targets")

        self.build_targets = build_targets or []

        # Enable offload targets for LLVM >= 18
        self.cuda_cc = []
        self.amd_gfx = []
        if self.cfg['build_openmp_offload'] and LooseVersion(self.version) >= '18':
            if self.nvptx_target_cond:
                if LooseVersion(self.version) < '20' and not cuda_cc_list:
                    raise EasyBuildError(
                        f"LLVM < 20 requires 'cuda_compute_capabilities' to build with {BUILD_TARGET_NVPTX}"
                    )
                self.cuda_cc = [cc.replace('.', '') for cc in cuda_cc_list]
                self.offload_targets += ['cuda']
                self.log.debug("Enabling `cuda` offload target")
            if self.amdgpu_target_cond:
                if LooseVersion(self.version) < '20' and not amd_gfx_list:
                    raise EasyBuildError(f"LLVM < 20 requires 'amd_gfx_list' to build with {BUILD_TARGET_AMDGPU}")
                self.amd_gfx = amd_gfx_list
                self.offload_targets += ['amdgpu']  # Used for LLVM >= 19
                self.log.debug("Enabling `amdgpu` offload target")

        self.general_opts['CMAKE_BUILD_TYPE'] = self.build_type
        self.general_opts['LLVM_TARGETS_TO_BUILD'] = self.list_to_cmake_arg(build_targets)

    def prepare_step(self, *args, **kwargs):
        """Prepare step, modified to ensure install dir is deleted before building"""
        super().prepare_step(*args, **kwargs)
        # re-create installation dir (deletes old installation),
        # Needed to ensure hardcoded rpath do not point to old installation during runtime builds and testing
        self.make_installdir()

    def _add_cmake_runtime_args(self):
        """Generate the value for 'RUNTIMES_CMAKE_ARGS' and add it to the cmake options."""
        args = []
        for key, val in self.runtimes_cmake_args.items():
            if isinstance(val, list):
                val = ' '.join(val)
            if val:
                args.append(f'-D{key}={val}')
        if args:
            self._cmakeopts['RUNTIMES_CMAKE_ARGS'] = self.list_to_cmake_arg(args)

    def _configure_general_build(self):
        """General configuration step for LLVM."""
        self._cmakeopts.update(self.general_opts)
        self._add_cmake_runtime_args()

    def _configure_intermediate_build(self):
        """Configure the intermediate stages of the build."""
        self._cmakeopts['LLVM_ENABLE_PROJECTS'] = self.list_to_cmake_arg(self.intermediate_projects)
        self._cmakeopts['LLVM_ENABLE_RUNTIMES'] = self.list_to_cmake_arg(self.intermediate_runtimes)

    def _configure_final_build(self):
        """Configure the final stage of the build."""
        self._cmakeopts['LLVM_ENABLE_PROJECTS'] = self.list_to_cmake_arg(self.final_projects)
        self._cmakeopts['LLVM_ENABLE_RUNTIMES'] = self.list_to_cmake_arg(self.final_runtimes)

        hwloc_root = get_software_root('hwloc')
        if hwloc_root:
            self.log.info("Using %s as hwloc root", hwloc_root)
            self._cmakeopts['LIBOMP_USE_HWLOC'] = 'ON'
            self._cmakeopts['LIBOMP_HWLOC_INSTALL_DIR'] = hwloc_root

        if 'openmp' in self.final_projects:
            if self.cfg['build_openmp_offload']:
                # Force dlopen of the GPU libraries at runtime, not using existing libraries
                if LooseVersion(self.version) >= '19':
                    self._cmakeopts['LIBOMPTARGET_PLUGINS_TO_BUILD'] = self.list_to_cmake_arg(self.offload_targets)
                    dlopen_plugins = set(self.offload_targets) & set(AVAILABLE_OFFLOAD_DLOPEN_PLUGIN_OPTIONS)
                    if dlopen_plugins:
                        self._cmakeopts['LIBOMPTARGET_DLOPEN_PLUGINS'] = self.list_to_cmake_arg(dlopen_plugins)
                else:
                    if self.amdgpu_target_cond:
                        self._cmakeopts['LIBOMPTARGET_FORCE_DLOPEN_LIBHSA'] = 'ON'
                    if self.nvptx_target_cond:
                        self._cmakeopts['LIBOMPTARGET_FORCE_DLOPEN_LIBCUDA'] = 'ON'
            self._cmakeopts['OPENMP_ENABLE_LIBOMPTARGET'] = 'ON'
            self._cmakeopts['LIBOMP_INSTALL_ALIASES'] = 'ON' if self.cfg['build_openmp_library_aliases'] else 'OFF'
            if not self.cfg['build_openmp_tools']:
                self._cmakeopts['OPENMP_ENABLE_OMPT_TOOLS'] = 'OFF'

        # Make sure tests are not running with more than 'parallel' tasks
        parallel = self.cfg.parallel
        if not build_option('mpi_tests'):
            parallel = 1
        lit_args = [f'-j {parallel}']
        if self.cfg['debug_tests']:
            lit_args += ['-v']
        timeout_single = self.cfg['test_suite_timeout_single']
        if timeout_single:
            lit_args += ['--timeout', str(timeout_single)]
        timeout_total = self.cfg['test_suite_timeout_total']
        if timeout_total:
            lit_args += ['--max-time', str(timeout_total)]
        self._cmakeopts['LLVM_LIT_ARGS'] = '"%s"' % ' '.join(lit_args)

        if self.cfg['use_polly']:
            self._cmakeopts['LLVM_POLLY_LINK_INTO_TOOLS'] = 'ON'
        if not self.cfg['skip_all_tests']:
            self._cmakeopts['LLVM_INCLUDE_TESTS'] = 'ON'
            self._cmakeopts['LLVM_BUILD_TESTS'] = 'ON'

    @staticmethod
    def _get_gcc_prefix():
        """Get the GCC prefix for the build."""
        arch = get_arch_prefix()
        gcc_root = get_software_root('GCCcore')
        gcc_version = get_software_version('GCCcore')
        # If that doesn't work, try with GCC
        if gcc_root is None:
            gcc_root = get_software_root('GCC')
            gcc_version = get_software_version('GCC')
        # If that doesn't work either, print error and exit
        if gcc_root is None:
            raise EasyBuildError("Can't find GCC or GCCcore to use")

        pattern = os.path.join(gcc_root, 'lib', 'gcc', f'{arch}-*', gcc_version)
        matches = glob.glob(pattern)
        if not matches:
            raise EasyBuildError("Can't find GCC version %s for architecture %s in %s", gcc_version, arch, pattern)
        gcc_prefix = os.path.abspath(matches[0])

        return gcc_root, gcc_prefix

    @staticmethod
    def _get_gcc_libpath(strict=False):
        """Get the GCC library path for the build."""
        gcc_root = get_software_root('GCCcore')
        if gcc_root is None:
            gcc_root = get_software_root('GCC')
        if gcc_root is None:
            if strict:
                raise EasyBuildError("Can't find GCC or GCCcore to use")
            else:
                print_msg("Can't find GCC or GCCcore to use, skipping setting of GCC library path", level=IGNORE)
                return ''
        return os.path.join(gcc_root, 'lib64')

    def _set_dynamic_linker(self):
        """Set the dynamic linker for the build if not the default one."""
        if self.sysroot:
            linkers = glob.glob(os.path.join(self.sysroot, '**', 'ld-*.so*'))
            for linker in linkers:
                if os.path.isfile(linker) and not os.path.islink(linker):
                    self.log.info("Using linker %s from sysroot", linker)
                    self.dynamic_linker = linker
                    break
            else:
                msg = f"No linker found in sysroot {self.sysroot}, using default linker"
                trace_msg(msg)
                self.log.warning(msg)

    def _update_test_ignore_patterns(self):
        """Update the ignore patterns based on known ignorable test failures when running with specific LLVM versions
        or with specific dependencies/options."""
        self.ignore_patterns = self.cfg['test_suite_ignore_patterns'] or []

        new_ignore_patterns = []
        if self.sysroot:
            # Some tests will run a FileCheck on the output of `clang -v` for `-internal-externc-isystem /usr/include`
            # where the path is hardcoded. If sysroot is set we replace that path by prepending the sysroot to it.
            # The changes needed varies from file to file and are not the same across versions.
            # Since this seems to be more of a problem with the test-suite settings than using the compilers
            # we can probably safely ignore these tests.
            known_driver_files = [
                'baremetal.cpp', 'csky-toolchain.c', 'freebsd-include-paths.c',
                'haiku.c', 'hexagon-toolchain-elf.c', 'hexagon-toolchain-linux.c',
                'mips-cs.cpp', 'mips-fsf.cpp', 'mips-img-v2.cpp', 'mips-img.cpp',
                'riscv32-toolchain-extra.c', 'riscv64-toolchain-extra.c',
                'rocm-detect.hip',
            ]
            known_frontend_files = [
                'warning-poison-system-directories.c'
            ]
            for file in known_driver_files:
                new_ignore_patterns.append(f'Clang :: Driver/{file}')
            for file in known_frontend_files:
                new_ignore_patterns.append(f'Clang :: Frontend/{file}')

            # Test related to config files, can fail due to overriding the default config file that we set to
            # ensure correct working with sysroot builds
            new_ignore_patterns.append('Flang :: Driver/config-file.f90')

        # See https://github.com/easybuilders/easybuild-easyblocks/pull/3741#issuecomment-2944852391
        # System-related failures due to /etc/timezone behavior
        new_ignore_patterns.append('llvm-libc++-shared.cfg.in :: std/time/time.zone/')

        # Can give different behavior based on system Scrt1.o
        new_ignore_patterns.append('Flang :: Driver/missing-input.f90')

        # See https://github.com/llvm/llvm-project/issues/140024
        if LooseVersion(self.version) <= '20.1.5':
            new_ignore_patterns.append('LLVM :: CodeGen/Hexagon/isel/pfalse-v4i1.ll')

        self.ignore_patterns += new_ignore_patterns
        self.log.info(f"Ignore patterns added due to known and ignorable test failures: {new_ignore_patterns}")

    def configure_step(self):
        """
        Install extra tools in bin/; enable zlib if it is a dep; optionally enable rtti; and set the build target
        """
        # Allow running with older versions of LLVM for minimal builds in order to replace EB_LLVM easyblock
        if not self.cfg['minimal'] and LooseVersion(self.version) < '18.1.6':
            raise EasyBuildError("LLVM version %s is not supported, please use version 18.1.6 or newer", self.version)

        # Allow running with older versions of GCC for minimal builds in order to replace EB_LLVM easyblock
        gcc_version = get_software_version('GCCcore')
        if not self.cfg['minimal'] and LooseVersion(gcc_version) < '13':
            raise EasyBuildError("LLVM %s requires GCC 13 or newer, found %s", self.version, gcc_version)

        # Lit is needed for running tests-suite
        lit_root = get_software_root('lit')
        if not lit_root and not self.cfg['skip_all_tests']:
            raise EasyBuildError("Can't find 'lit', needed for running tests-suite")

        timeouts = self.cfg['test_suite_timeout_single'] or self.cfg['test_suite_timeout_total']
        if not self.cfg['skip_all_tests'] and timeouts:
            psutil_root = get_software_root('psutil')
            if not psutil_root:
                raise EasyBuildError("Can't find 'psutil', needed for running tests-suite with timeout")

        # Parallel build
        self.make_parallel_opts = ""
        if self.cfg.parallel:
            self.make_parallel_opts = f"-j {self.cfg.parallel}"

        self._configure_build_targets()

        # Sysroot
        self.sysroot = build_option('sysroot')
        if self.sysroot:
            if LooseVersion(self.version) < '19':
                raise EasyBuildError("Using sysroot is not supported by EasyBuild for LLVM < 19")
            self.general_opts['DEFAULT_SYSROOT'] = self.sysroot
            self.general_opts['CMAKE_SYSROOT'] = self.sysroot
            self._set_dynamic_linker()
            trace_msg(f"Using '{self.dynamic_linker}' as dynamic linker from sysroot {self.sysroot}")

        # CMAKE_INSTALL_PREFIX and LLVM start directory are set here instead of in __init__ to
        # ensure this easyblock can be used as a Bundle component, see
        # https://github.com/easybuilders/easybuild-easyblocks/issues/3680
        self.general_opts['CMAKE_INSTALL_PREFIX'] = self.installdir

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

        self.general_opts['LLVM_ENABLE_ASSERTIONS'] = 'ON' if self.cfg['assertions'] else 'OFF'

        # Dependencies based persistent options (should be reused across stages)
        # Libxml2
        xml2_root = get_software_root('libxml2')
        # Explicitly disable libxml2 if not found to avoid linking against system libxml2
        if xml2_root:
            if self.full_llvm:
                self.log.warning("LLVM is being built in 'full_llvm' mode, libxml2 will not be used")
                self.general_opts['LLVM_ENABLE_LIBXML2'] = 'OFF'
            else:
                self.general_opts['LLVM_ENABLE_LIBXML2'] = 'ON'
        else:
            self.general_opts['LLVM_ENABLE_LIBXML2'] = 'OFF'

        # If 'ON', risk finding a system zlib or zstd leading to including /usr/include as -isystem that can lead
        # to errors during compilation of 'offload.tools.kernelreplay' due to the inclusion of LLVMSupport (19.x)
        self.general_opts['LLVM_ENABLE_ZLIB'] = 'ON' if get_software_root('zlib') else 'OFF'
        self.general_opts['LLVM_ENABLE_ZSTD'] = 'ON' if get_software_root('zstd') else 'OFF'
        # Should not use system SWIG if present
        self.general_opts['LLDB_ENABLE_SWIG'] = 'ON' if get_software_root('SWIG') else 'OFF'

        # Avoid using system `gdb` in case it is not provided as a dependency
        # This could cause the wrong sysroot/dynamic linker being picked up in a sysroot build causing tests to fail
        self.general_opts['LIBOMP_OMPD_GDB_SUPPORT'] = 'ON' if get_software_root('GDB') else 'OFF'

        z3_root = get_software_root("Z3")
        if z3_root:
            self.log.info("Using %s as Z3 root", z3_root)
            self.general_opts['LLVM_ENABLE_Z3_SOLVER'] = 'ON'
            self.general_opts['LLVM_Z3_INSTALL_DIR'] = z3_root
        else:
            self.general_opts['LLVM_ENABLE_Z3_SOLVER'] = 'OFF'

        # update ignore patterns for ignorable test failures
        self._update_test_ignore_patterns()

        python_opts = get_cmake_python_config_dict()
        self.general_opts.update(python_opts)
        self.runtimes_cmake_args.update(python_opts)

        if self.cfg['bootstrap']:
            self._configure_intermediate_build()
        else:
            self._configure_final_build()

        if self.cfg['skip_sanitizer_tests'] and build_option('strict') != ERROR:
            self.log.info("Disabling the sanitizer tests")
            self.disable_sanitizer_tests()

        # Remove python bindings tests causing uncaught exception in the build
        cmakelists_tests = os.path.join(self.start_dir, 'clang', 'CMakeLists.txt')
        regex_subs = []
        regex_subs.append((r'add_subdirectory\(bindings/python/tests\)', ''))
        apply_regex_substitutions(cmakelists_tests, regex_subs)

        # Remove flags disabling the use of configuration files during compiler-rt tests as we in general rely on them
        # (see https://github.com/easybuilders/easybuild-easyblocks/pull/3741#issuecomment-2939404304)
        lit_cfg_file = os.path.join(self.start_dir, 'compiler-rt', 'test', 'lit.common.cfg.py')
        regex_subs = [
            (r'^if config.has_no_default_config_flag:', ''),
            (r'^\s*config.environment\["CLANG_NO_DEFAULT_CONFIG"\] = "1"', '')
        ]
        apply_regex_substitutions(lit_cfg_file, regex_subs)

        # For LLVM 18+ config files should be used and this option is deprecated and causes an error in 19
        # But the --gcc-toolchain and --gcc-install-dir for flang are not supported before LLVM 19
        # https://github.com/llvm/llvm-project/pull/87360
        if LooseVersion(self.version) < '19':
            self.log.debug("Using GCC_INSTALL_PREFIX")
            self.general_opts['GCC_INSTALL_PREFIX'] = self.gcc_root
        else:
            # See https://github.com/llvm/llvm-project/pull/85891#issuecomment-2021370667
            self.log.debug("Using '--gcc-install-dir' in CMAKE_C_FLAGS and CMAKE_CXX_FLAGS")
            self.runtimes_cmake_args['CMAKE_C_FLAGS'] += [f'--gcc-install-dir={self.gcc_prefix}']
            self.runtimes_cmake_args['CMAKE_CXX_FLAGS'] += [f'--gcc-install-dir={self.gcc_prefix}']

        # If we don't want to build with CUDA (not in dependencies) trick CMakes FindCUDA module into not finding it by
        # using the environment variable which is used as-is and later checked for a falsy value when determining
        # whether CUDA was found
        if not get_software_root('CUDA'):
            setvar('CUDA_NVCC_EXECUTABLE', 'IGNORE')

        # 20.1+ uses a generic IR for OpenMP DeviceRTL
        if self.cfg['build_openmp_offload'] and LooseVersion(self.version) < '20.1':
            gpu_archs = self.cfg.get_cuda_cc_template_value("cuda_sm_space_sep", required=False).split()
            gpu_archs += self.amd_gfx
            if gpu_archs:
                self.general_opts['LIBOMPTARGET_DEVICE_ARCHITECTURES'] = self.list_to_cmake_arg(gpu_archs)

        self._configure_general_build()
        self.add_cmake_opts()

        src_dir = os.path.join(self.start_dir, 'llvm')
        output = super().configure_step(builddir=self.llvm_obj_dir_stage1, srcdir=src_dir)

        # Get LLVM_HOST_TRIPLE (e.g. x86_64-unknown-linux-gnu) from the output
        for line in output.splitlines():
            if 'llvm host triple' in line.lower():
                self.host_triple = line.split(':')[1].strip()
                break
        else:
            # LLVM_HOST_TRIPLE needs to be set when building runtimes or bootstrapping.
            if self.cfg['build_runtimes'] or self.cfg['bootstrap']:
                raise EasyBuildError("`LLVM_HOST_TRIPLE` not found in the output of the configure step")
            # Otherwise it can be inferred a posteriori from the install directory
            else:
                self.log.warning("`LLVM_HOST_TRIPLE` not found in the output of the configure step")

        if not self.cfg['bootstrap']:
            if build_option('rpath') and self._cmakeopts['LLVM_ENABLE_RUNTIMES'] != '""':
                # Ensure RPATH wrappers are used for the runtimes also at the first stage
                # Call configure again now that the host triple is known from the previous configure call
                remove_dir(self.llvm_obj_dir_stage1)
                self._prepare_runtimes_rpath_wrappers(self.llvm_obj_dir_stage1)
                self.add_cmake_opts()
                trace_msg("Reconfiguring LLVM to use the RPATH wrappers for the runtimes")
                super().configure_step(builddir=self.llvm_obj_dir_stage1, srcdir=src_dir)
            # Pre-create the CFG files in the `build_stage/bin` directory to enforce using the correct dynamic
            # linker in case of sysroot builds, and to ensure the correct GCC installation is used also for the
            # runtimes (which would otherwise use the system default dynamic linker)
            self._create_compiler_config_file(self.llvm_obj_dir_stage1)

    def disable_sanitizer_tests(self):
        """Disable the tests of all the sanitizers by removing the test directories from the build system"""
        cmakelists_tests = os.path.join(self.start_dir, 'compiler-rt', 'test', 'CMakeLists.txt')
        regex_subs = [(r'compiler_rt_test_runtime.*san.*', '')]
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
            self._cmakeopts.update(self.remove_gcc_dependency_opts)

    def configure_step3(self):
        """Configure the third stage of the bootstrap."""
        self._cmakeopts = {}
        self._configure_general_build()
        self._configure_final_build()
        # Update runtime CMake arguments, as they might have
        # changed when configuring the final build arguments
        self._add_cmake_runtime_args()
        if self.full_llvm:
            self._cmakeopts.update(self.remove_gcc_dependency_opts)

    def _create_compiler_config_file(self, installdir):
        """Create a config file for the compiler to point to the correct GCC installation."""

        # This is only needed for LLVM >= 19, as the --gcc-install-dir option was introduced then
        if LooseVersion(self.version) < '19':
            return

        bin_dir = os.path.join(installdir, 'bin')
        opts = [f'--gcc-install-dir={self.gcc_prefix}']

        if self.dynamic_linker:
            opts.append(f'-Wl,-dynamic-linker,{self.dynamic_linker}')
            # The --dyld-prefix flag exists, but beside being poorly documented it is also not supported by flang
            # https://reviews.llvm.org/D851
            # prefix = self.sysroot.rstrip('/')
            # opts.append(f'--dyld-prefix={prefix}')

        # Check, for a non `full_llvm` build, if GCCcore is in the LIBRARY_PATH, and if not add it;
        # This is needed as the runtimes tests will not add the -L option to the linker command line for GCCcore
        # otherwise
        if not self.full_llvm:
            gcc_lib = self._get_gcc_libpath(strict=True)
            lib_path = os.getenv('LIBRARY_PATH', '')
            if gcc_lib not in lib_path:
                self.log.info("Adding GCCcore libraries location `%s` the config files", gcc_lib)
                opts.append(f'-L{gcc_lib}')

        for comp in self.cfg_compilers:
            write_file(os.path.join(bin_dir, f'{comp}.cfg'), ' '.join(opts))

    def build_with_prev_stage(self, prev_dir, stage_dir):
        """Build LLVM using the previous stage."""
        curdir = os.getcwd()

        bin_dir = os.path.join(prev_dir, 'bin')
        lib_dir_runtime = self.get_runtime_lib_path(prev_dir)

        # Give priority to the libraries in the current stage if compiled to avoid failures due to undefined symbols
        # e.g. when calling the compiled clang-ast-dump for stage 3
        lib_path = ':'.join(filter(None, [
            os.path.join(stage_dir, lib_dir_runtime),
            os.path.join(prev_dir, lib_dir_runtime),
        ]))

        if build_option('rpath'):
            self._prepare_runtimes_rpath_wrappers(stage_dir)

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

            if self.full_llvm:
                # See  https://github.com/llvm/llvm-project/issues/111667
                to_add = '--unwindlib=none'
                flags = self.runtimes_cmake_args['CMAKE_EXE_LINKER_FLAGS']
                if to_add not in flags:
                    flags.append(to_add)

                self._add_cmake_runtime_args()

            # determine full path to clang/clang++ (which may be wrapper scripts in case of RPATH linking)
            clang = which('clang')
            clangxx = which('clang++')

            self._cmakeopts['CMAKE_C_COMPILER'] = clang
            self._cmakeopts['CMAKE_CXX_COMPILER'] = clangxx
            self._cmakeopts['CMAKE_ASM_COMPILER'] = clang
            self._cmakeopts['CMAKE_ASM_COMPILER_ID'] = 'Clang'

            self._create_compiler_config_file(prev_dir)
            # also pre-create the CFG files in the `build_stage/bin` directory to enforce using the correct dynamic
            # linker in case of sysroot builds, and to ensure the correct GCC installation is used also for the
            # runtimes (which would otherwise use the system default dynamic linker)
            self._create_compiler_config_file(stage_dir)

            self.add_cmake_opts()

            change_dir(stage_dir)
            self.log.debug("Configuring %s", stage_dir)
            cmd = ' '.join(['cmake', self.cfg['configopts'], os.path.join(self.start_dir, 'llvm')])
            run_shell_cmd(cmd)

            self.log.debug("Building %s", stage_dir)
            cmd = f"make {self.make_parallel_opts} VERBOSE=1"
            res = run_shell_cmd(cmd, fail_on_error=False)
            # Observed in 20.1.0, the build of the offloading tools can fail due to 'cstdint' file not found
            # But will succeed if executed again with -j 1 (possible missing dependency in the CMake logic?)
            # See https://github.com/llvm/llvm-project/issues/130783
            if res.exit_code != EasyBuildExit.SUCCESS:
                self.log.warning("Build failed, attempting again with parallel ON")
                res = run_shell_cmd(cmd, fail_on_error=False)
            if res.exit_code != EasyBuildExit.SUCCESS:
                self.log.warning("Build failed, attempting again with parallel OFF")
                cmd = "make -j 1 VERBOSE=1"
                res = run_shell_cmd(cmd)

        change_dir(curdir)

    def _prepare_runtimes_rpath_wrappers(self, stage_dir):
        """Run the build command also ensuring proper rpath-ing for the Runtime build.

        Binaries and libraries produced during runtimes make use of the newly built Clang compiler which is not
        rpath-wrapped. This causes the executable to be produced without rpath (if required) and with
        runpath set to $ORIGIN. This causes 2 problems:
         - Binaries produced for the runtimes will fail the sanity check
         - Runtimes libraries that link to libLLVM.so like 'libomptarget.so' need LD_LIBRARY_PATH to work.
           This is because even if an executable compiled with the new llvm has rpath pointing to $EBROOTLLVM/lib,
           it will not be resolved with the executable's rpath, but the library's runpath
           (rpath is ignored if runpath is set).
           Even if libLLVM.so is a direct dependency of the executable, it needs to be resolved both for the
           executable and the library.

        Here we create a mock binary for the current stage, rpath-wrap it and than pass the rpath-wrapped binary
        to the runtimes build as the compiler through RUNTIMES_CMAKE_ARGS.
        """
        lib_dir_runtime = self.get_runtime_lib_path(stage_dir, fail_ok=True)

        # Give priority to the libraries in the current stage if compiled to avoid failures due to undefined symbols
        # e.g. when calling the compiled clang-ast-dump for stage 3
        lib_path = os.path.join(stage_dir, lib_dir_runtime)

        bin_dir_new = os.path.join(stage_dir, 'bin')
        mkdir(bin_dir_new, parents=True)
        with _wrap_env(bin_dir_new, lib_path):
            nxt_clang = os.path.join(bin_dir_new, 'clang')
            nxt_clangxx = os.path.join(bin_dir_new, 'clang++')
            with open(nxt_clang, 'w', encoding='utf-8') as f:
                f.write("#!/bin/bash\n")
                f.write("echo 'MOCK clang'\n")
            adjust_permissions(nxt_clang, stat.S_IXUSR)
            with open(nxt_clangxx, 'w', encoding='utf-8') as f:
                f.write("#!/bin/bash\n")
                f.write("echo 'MOCK clangxx'\n")
            adjust_permissions(nxt_clangxx, stat.S_IXUSR)

            tmp_toolchain = Clang(name='Clang', version='1')
            # Don't need stage dir here as LD_LIBRARY_PATH is set during build, this is only needed for
            # installed binaries with rpath
            lib_dirs = [os.path.join(self.installdir, x) for x in SEARCH_PATH_LIB_DIRS + [lib_dir_runtime]]
            tmp_toolchain.prepare_rpath_wrappers(rpath_include_dirs=lib_dirs)
            remove_file(nxt_clang)
            remove_file(nxt_clangxx)
            msg = "Prepared MOCK rpath wrappers needed to rpath-wrap also the new compilers produced "
            msg += "by the project build and than used for the runtimes build"
            self.log.info(msg)
            clang_mock = which('clang')
            clangxx_mock = which('clang++')

            clang_mock_wrapper_dir = os.path.dirname(clang_mock)

            symlink(os.path.join(stage_dir, 'opt'), os.path.join(clang_mock_wrapper_dir, 'opt'))

            # Use mocked rpath wrappers
            self.runtimes_cmake_args['CMAKE_C_COMPILER'] = [clang_mock]
            self.runtimes_cmake_args['CMAKE_CXX_COMPILER'] = [clangxx_mock]

        self._add_cmake_runtime_args()

    def build_step(self, *args, **kwargs):
        """Build LLVM, and optionally build it using itself."""
        if self.cfg['bootstrap']:
            self.log.info("Building stage 1")
            print_msg("Building stage 1/3")
        else:
            self.log.info("Building LLVM")
            print_msg("Building stage 1/1")

        change_dir(self.llvm_obj_dir_stage1)
        super().build_step(*args, **kwargs)

        if self.cfg['bootstrap']:
            self.log.info("Building stage 2")
            print_msg("Building stage 2/3")
            self.configure_step2()
            self.build_with_prev_stage(self.llvm_obj_dir_stage1, self.llvm_obj_dir_stage2)

            self.log.info("Building stage 3")
            print_msg("Building stage 3/3")
            self.configure_step3()
            self.build_with_prev_stage(self.llvm_obj_dir_stage2, self.llvm_obj_dir_stage3)

    def _para_test_step(self, parallel=1):
        """Run test suite with the specified number of parallel jobs for make."""
        basedir = self.final_dir

        # From grep -E "^[A-Z]+: " LOG_FILE | cut -d: -f1 | sort | uniq
        OUTCOME_FAIL = [
            'FAIL',
            'TIMEOUT',
        ]
        # OUTCOME_OK = [
        #     'PASS',
        #     'UNSUPPORTED',
        #     'XFAIL',
        # ]

        change_dir(basedir)
        lib_path = ''
        if self.cfg['build_runtimes']:
            lib_dir_runtime = self.get_runtime_lib_path(basedir)
            lib_path = os.path.join(basedir, lib_dir_runtime)
        if not self.full_llvm:
            # Add the GCC library path to the LD_LIBRARY_PATH if it is not already there to ensure correct
            # libstdc++ and libgcc_s.so are used for tests
            gcc_lib = self._get_gcc_libpath(strict=True)
            lib_path = ':'.join(filter(None, [gcc_lib, lib_path]))

        with _wrap_env(os.path.join(basedir, 'bin'), lib_path):
            cmd = f"make -j {parallel} check-all"
            res = run_shell_cmd(cmd, fail_on_error=False)
            out = res.output
            self.log.debug(out)

        ignore_patterns = self.ignore_patterns
        ignored_pattern_matches = 0
        failed_pattern_matches = 0
        if ignore_patterns:
            for line in out.splitlines():
                if any(line.startswith(f'{x}: ') for x in OUTCOME_FAIL):
                    if any(patt in line for patt in ignore_patterns):
                        self.log.info("Ignoring test failure: %s", line)
                        ignored_pattern_matches += 1
                    failed_pattern_matches += 1

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

        if num_failed is not None:
            num_timed_out = 0
            rgx_timed_out = re.compile(r'^ +Timed Out +: +([0-9]+)', flags=re.MULTILINE)
            mch = rgx_timed_out.search(out)
            if mch is not None:
                num_timed_out = int(mch.group(1))
                self.log.info("Tests timed out: %s", num_timed_out)
            num_failed += num_timed_out

        if num_failed != failed_pattern_matches:
            msg = f"Number of failed tests ({num_failed}) does not match "
            msg += f"Number identified via line-by-line pattern matching: {failed_pattern_matches}"
            self.log.warning(msg)

        if num_failed is not None and ignored_pattern_matches:
            self.log.info("Ignored %s failed tests due to ignore patterns", ignored_pattern_matches)
            num_failed -= ignored_pattern_matches

        return num_failed

    def test_step(self):
        """Run tests on final stage (unless disabled)."""
        if not self.cfg['skip_all_tests']:
            # Also runs of test suite compilers should be made aware of the GCC installation
            self._create_compiler_config_file(self.final_dir)

            # For nvptx64 tests, find out if 'ptxas' exists in $PATH. If not, ignore all nvptx64 test failures
            if not which('ptxas', on_error=IGNORE):
                self.ignore_patterns += ['nvptx64-nvidia-cuda', 'nvptx64-nvidia-cuda-LTO']
                self.log.warning("PTXAS not found in PATH, ignoring failing tests for NVPTX target")
            # If the AMDGPU target is built, tests will be run if libhsa-runtime64.so is found.
            # However, this can cause issues if the system libraries are used, due to other loaded modules.
            # Therefore, ignore failing tests if ROCr-Runtime is not in the dependencies and
            # warn about this in the logs.
            if 'rocr-runtime' not in self.deps:
                self.ignore_patterns += ['amdgcn-amd-amdhsa']
                self.log.warning("ROCr-Runtime not in dependencies, ignoring failing tests for AMDGPU target.")

            max_failed = self.cfg['test_suite_max_failed']
            num_failed = self._para_test_step(parallel=1)
            if num_failed is None:
                self.report_test_failure("Failed to extract test results from output")
                return

            if num_failed > max_failed:
                self.report_test_failure(f"Too many failed tests: {num_failed} ({max_failed} allowed)")
            elif num_failed:
                self.log.info(f"Test suite completed with {num_failed} failed tests ({max_failed} allowed)")
            else:
                self.log.info(f"Test suite completed, no failed tests ({max_failed} allowed)")

    def install_step(self):
        """Install stage 1 or 3 (if bootstrap) binaries."""
        basedir = self.final_dir
        change_dir(basedir)

        if self.cfg['build_runtimes']:
            orig_ld_library_path = os.getenv('LD_LIBRARY_PATH')
            lib_dir_runtime = self.get_runtime_lib_path(basedir)

            lib_path = ':'.join([
                os.path.join(basedir, lib_dir_runtime),
                orig_ld_library_path
            ])

            self.cfg.update('preinstallopts', f'LD_LIBRARY_PATH={lib_path}')

        super().install_step()

        # copy Python bindings here in post-install step so that it is not done more than once in multi_deps context
        if self.cfg['python_bindings']:
            python_bindings_source_dir = os.path.join(self.start_dir, 'clang', 'bindings', 'python')
            python_bindins_target_dir = os.path.join(self.installdir, 'lib', 'python')
            copy_dir(python_bindings_source_dir, python_bindins_target_dir, dirs_exist_ok=True)

            python_bindings_source_dir = os.path.join(self.start_dir, 'mlir', 'python')
            copy_dir(python_bindings_source_dir, python_bindins_target_dir, dirs_exist_ok=True)

        # For GCC aware installation create config files in order to point to the correct GCC installation
        # Required as GCC_INSTALL_PREFIX was removed (see https://github.com/llvm/llvm-project/pull/87360)
        self._create_compiler_config_file(self.installdir)

        # This is needed as some older build system will select a different naming scheme for the library leading to
        # The correct target <__config_site> and libclang_rt.builtins.a not being found
        # An example is building BOOST
        resdir_version = self.version.split('.')[0]
        clang_lib = os.path.join(self.installdir, 'lib', 'clang', resdir_version, 'lib')

        for orig, other in self.symlink_lst:
            for dirname in ['include', 'lib', clang_lib]:
                src = os.path.join(self.installdir, dirname, orig)
                dst = os.path.join(self.installdir, dirname, other)
                if os.path.exists(src) and not os.path.exists(dst):
                    msg = f"Creating symlink for {src} to {dst} for better compatibility with expected --target"
                    self.log.info(msg)
                    symlink(src, dst)

    def get_runtime_lib_path(self, base_dir, fail_ok=False):
        """Return the path to the runtime libraries."""
        if self.host_triple is None:
            # Attempt using the glob based detection of the runtime library directory for runs of
            # --sanity-check-only/--module-only where the configure step is not used
            arch = get_arch_prefix()
            matches = glob.glob(os.path.join(base_dir, 'lib', f'{arch}-*'))
            if matches:
                self.host_triple = os.path.basename(matches[0])
            else:
                raise EasyBuildError("Could not find runtime library directory")

        res = os.path.join('lib', self.host_triple)
        if not fail_ok:
            path = os.path.join(base_dir, res)
            if not os.path.exists(path):
                raise EasyBuildError("Could not find runtime library directory '%s'", path)

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

    @staticmethod
    def _sanity_check_gcc_prefix(compilers, gcc_prefix, installdir):
        """Check if the GCC prefix of the compiler is correct"""
        rgx = re.compile('Selected GCC installation: (.*)')
        for comp in compilers:
            cmd = "%s -v" % os.path.join(installdir, 'bin', comp)
            res = run_shell_cmd(cmd, fail_on_error=False)
            out = res.output
            mch = rgx.search(out)
            if mch is None:
                raise EasyBuildError("Failed to extract GCC installation path from output of '%s': %s", cmd, out)
            check_prefix = mch.group(1)
            if check_prefix != gcc_prefix:
                error_msg = f"GCC installation path '{check_prefix}' does not match expected path '{gcc_prefix}'"
                raise EasyBuildError(error_msg)

    def _sanity_check_dynamic_linker(self):
        """Check if the dynamic linker is correct."""
        if self.sysroot:
            # compile & test trivial C program to verify that works
            test_fn = 'test123'
            test_txt = '#include <stdio.h>\n'
            test_txt += 'int main() { printf("Hello World\\n"); return 0; }\n'
            write_file(test_fn + '.c', test_txt)

            clang = os.path.join(self.installdir, 'bin', 'clang')
            cmd = f"{clang} -o {test_fn}.o -c {test_fn}.c"
            run_shell_cmd(cmd, fail_on_error=True)

            cmd = f"{clang} -v -o {test_fn}.x {test_fn}.o"
            res = run_shell_cmd(cmd, fail_on_error=True)
            out = res.output

            # Check if the dynamic linker is set to the sysroot
            if self.sysroot not in out:
                error_msg = f"Dynamic linker is not set to the sysroot '{self.sysroot}'"
                raise EasyBuildError(error_msg)

            cmd = f'./{test_fn}.x'
            res = run_shell_cmd(cmd, fail_on_error=False)
            if res.exit_code != EasyBuildExit.SUCCESS:
                error_msg = f"Failed to run the compiled executable '{cmd}' for testing the dynamic linker"
                raise EasyBuildError(error_msg)

            for suffix in ('.c', '.o', '.x'):
                remove_file(f'{test_fn}{suffix}')

    def sanity_check_step(self, custom_paths=None, custom_commands=None, *args, **kwargs):
        """Perform sanity checks on the installed LLVM."""
        lib_dir_runtime = None
        if self.cfg['build_runtimes']:
            lib_dir_runtime = self.get_runtime_lib_path(self.installdir)
        shlib_ext = '.' + get_shared_lib_ext()

        resdir_version = self.version.split('.')[0]
        version = LooseVersion(self.version)

        arch = get_cpu_architecture()
        # Check architecture explicitly since Clang uses potentially different names
        if arch == X86_64:
            arch = 'x86_64'
        elif arch == POWER:
            arch = 'ppc64'
        elif arch == AARCH64:
            arch = 'aarch64'
        else:
            print_warning("Unknown CPU architecture (%s) for OpenMP and runtime libraries check!" % arch, log=self.log)

        check_files = []
        check_bin_files = []
        check_lib_files = []
        check_librt_files = []
        check_inc_files = []
        check_dirs = ['include/llvm', 'include/llvm-c', 'lib/cmake/llvm']
        custom_commands = [
            "llvm-ar --help",
            "llvm-ranlib --help",
            "llvm-nm --help",
            "llvm-objdump --help",
        ]
        gcc_prefix_compilers = []
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
            custom_commands += ['llvm-config --cxxflags', 'clang --help', 'clang++ --help']
            gcc_prefix_compilers += ['clang', 'clang++']

        if 'clang-tools-extra' in self.final_projects:
            # clang-pseudo removed with LLVM 20
            check_bin_files += [
                'clangd', 'clang-tidy', 'clang-include-fixer', 'clang-query', 'clang-move',
                'clang-reorder-fields', 'clang-include-cleaner', 'clang-apply-replacements',
                'clang-change-namespace', 'pp-trace', 'modularize'
            ]
            check_lib_files += [
                'libclangTidy.a', 'libclangQuery.a', 'libclangIncludeFixer.a', 'libclangIncludeCleaner.a',
            ]
            check_dirs += ['include/clang-tidy']
        if 'flang' in self.final_projects:
            if version < '19':
                check_bin_files += ['bbc', 'flang-new', 'flang-to-external-fc', 'f18-parse-demo', 'fir-opt', 'tco']
            else:
                check_bin_files += ['bbc', 'flang-new', 'f18-parse-demo', 'fir-opt', 'tco']
            check_lib_files += [
                'libFortranRuntime.a', 'libFortranSemantics.a', 'libFortranLower.a', 'libFortranParser.a',
                'libFIRCodeGen.a', 'libflangFrontend.a', 'libFortranCommon.a', 'libFortranDecimal.a',
                'libHLFIRDialect.a'
            ]
            check_dirs += ['lib/cmake/flang', 'include/flang']
            custom_commands += ['bbc --help', 'mlir-tblgen --help', 'flang-new --help']
            gcc_prefix_compilers += ['flang-new']

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
        if 'libunwind' in self.final_runtimes:
            check_librt_files += ['libunwind.a']
            if self.build_shared:
                check_librt_files += ['libunwind.so']
            check_inc_files += ['unwind.h', 'libunwind.h', 'mach-o/compact_unwind_encoding.h']
        if 'libcxx' in self.final_runtimes:
            check_librt_files += ['libc++.a']
            if self.build_shared:
                check_librt_files += ['libc++.so']
            check_dirs += ['include/c++/v1']
        if 'libcxxabi' in self.final_runtimes:
            check_librt_files += ['libc++abi.a']
            if self.build_shared:
                check_librt_files += ['libc++abi.so']

        if 'polly' in self.final_projects:
            check_lib_files += ['libPolly.a', 'libPollyISL.a']
            if self.build_shared:
                check_lib_files += ['LLVMPolly.so']
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
            custom_commands += ['llvm-bolt --help']
        if 'openmp' in self.final_projects:
            omp_lib_files = ['libomp.so', 'libompd.so']
            if self.cfg['build_openmp_offload']:
                omp_lib_files += ['libomptarget.so']
                # In LLVM 19, the omptarget plugins (rtl.<device>.so) are built as static libraries
                # and linked into the libomptarget.so shared library
                if version < '19':
                    omp_lib_files += [f'libomptarget.rtl.{arch}.so']
                if self.nvptx_target_cond:
                    if version < '19':
                        omp_lib_files += ['libomptarget.rtl.cuda.so']
                    if version < '20':
                        omp_lib_files += [f'libomptarget-nvptx-sm_{cc}.bc' for cc in self.cuda_cc]
                    else:
                        omp_lib_files += ['libomptarget-nvptx.bc']
                if self.amdgpu_target_cond:
                    if version < '19':
                        omp_lib_files += ['libomptarget.rtl.amdgpu.so']
                    if version < '20':
                        omp_lib_files += [f'libomptarget-amdgpu-{gfx}.bc' for gfx in self.amd_gfx]
                    else:
                        omp_lib_files += ['libomptarget-amdgpu.bc']
                check_bin_files += ['llvm-omp-kernel-replay']
                if version < '20':
                    check_bin_files += ['llvm-omp-device-info']
                else:
                    check_bin_files += ['llvm-offload-device-info']
            if version < '19':
                # Before LLVM 19, omp related libraries are installed under 'ROOT/lib''
                check_lib_files += omp_lib_files
            else:
                # Starting from LLVM 19, omp related libraries are installed the runtime library directory
                check_librt_files += omp_lib_files

        if self.cfg['build_openmp_tools']:
            check_files += [os.path.join('lib', 'clang', resdir_version, 'include', 'ompt.h')]
            if version < '19':
                check_lib_files += ['libarcher.so']
            else:
                check_librt_files += ['libarcher.so']
        if self.cfg['python_bindings']:
            custom_commands += ["python -c 'import clang'"]
            custom_commands += ["python -c 'import mlir'"]

        check_files.extend(os.path.join('bin', x) for x in check_bin_files)
        check_files.extend(os.path.join('lib', x) for x in check_lib_files)
        check_files.extend(os.path.join(lib_dir_runtime, x) for x in check_librt_files)
        check_files.extend(os.path.join('include', x) for x in check_inc_files)

        so_libs = [lib for lib in check_files if lib.endswith('.so')]
        for libso in so_libs:
            libext = libso.replace('.so', shlib_ext)
            if libext not in check_files:
                check_files.remove(libso)
                check_files.append(libext)

        custom_paths = {
            'files': check_files,
            'dirs': check_dirs,
        }

        if lib_dir_runtime:
            # Required for 'clang -v' to work if linked to LLVM runtimes
            with _wrap_env(ld_path=os.path.join(self.installdir, lib_dir_runtime)):
                self._sanity_check_gcc_prefix(gcc_prefix_compilers, self.gcc_prefix, self.installdir)
                self._sanity_check_dynamic_linker()
        else:
            self._sanity_check_gcc_prefix(gcc_prefix_compilers, self.gcc_prefix, self.installdir)
            self._sanity_check_dynamic_linker()

        return super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands, *args, **kwargs)

    def make_module_step(self, *args, **kwargs):
        """
        Clang can find its own headers and libraries but the shared libraries need to be in $LD_LIBRARY_PATH
        """
        mod_env_headers = self.module_load_environment.alias_vars(MODULE_LOAD_ENV_HEADERS)
        for disallowed_var in mod_env_headers:
            self.module_load_environment.remove(disallowed_var)
            self.log.debug(f"Purposely not updating ${disallowed_var} in {self.name} module file")

        lib_dirs = SEARCH_PATH_LIB_DIRS[:]
        if self.cfg['build_runtimes']:
            runtime_lib_path = self.get_runtime_lib_path(self.installdir)
            lib_dirs.append(runtime_lib_path)

        self.log.debug(f"List of subdirectories for libraries to add to $LD_LIBRARY_PATH + $LIBRARY_PATH: {lib_dirs}")
        self.module_load_environment.LD_LIBRARY_PATH = lib_dirs
        self.module_load_environment.LIBRARY_PATH = lib_dirs

        return super().make_module_step(*args, **kwargs)

    def make_module_extra(self):
        """Custom variables for Clang module."""
        txt = super().make_module_extra()
        # we set the symbolizer path so that asan/tsan give meanfull output by default
        asan_symbolizer_path = os.path.join(self.installdir, 'bin', 'llvm-symbolizer')
        txt += self.module_generator.set_environment('ASAN_SYMBOLIZER_PATH', asan_symbolizer_path)
        if self.cfg['python_bindings']:
            txt += self.module_generator.prepend_paths('PYTHONPATH', os.path.join('lib', 'python'))
        return txt
