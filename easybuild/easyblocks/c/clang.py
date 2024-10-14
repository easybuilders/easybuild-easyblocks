##
# Copyright 2013-2024 Dmitri Gribenko
# Copyright 2013-2024 Ghent University
#
# This file is triple-licensed under GPLv2 (see below), MIT, and
# BSD three-clause licenses.
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
Support for building and installing Clang, implemented as an easyblock.

@author: Dmitri Gribenko (National Technical University of Ukraine "KPI")
@author: Ward Poelmans (Ghent University)
@author: Alan O'Cais (Juelich Supercomputing Centre)
@author: Maxime Boissonneault (Digital Research Alliance of Canada, Universite Laval)
"""

import glob
import os
import shutil
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.toolchains.compiler.clang import Clang
from easybuild.tools import run
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, mkdir, symlink, which
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import AARCH32, AARCH64, POWER, RISCV64, X86_64
from easybuild.tools.systemtools import get_cpu_architecture, get_os_name, get_os_version, get_shared_lib_ext
from easybuild.tools.environment import setvar

# List of all possible build targets for Clang
CLANG_TARGETS = ["all", "AArch64", "AMDGPU", "ARM", "CppBackend", "Hexagon", "Mips",
                 "MBlaze", "MSP430", "NVPTX", "PowerPC", "R600", "RISCV", "Sparc",
                 "SystemZ", "X86", "XCore"]

# Mapping of EasyBuild CPU architecture names to list of default LLVM target names
DEFAULT_TARGETS_MAP = {
    AARCH32: ['ARM'],
    AARCH64: ['AArch64'],
    POWER: ['PowerPC'],
    RISCV64: ['RISCV'],
    X86_64: ['X86'],
}

# List of all possible AMDGPU gfx targets supported by LLVM
AMDGPU_GFX_SUPPORT = ['gfx700', 'gfx701', 'gfx801', 'gfx803', 'gfx900',
                      'gfx902', 'gfx906', 'gfx908', 'gfx90a', 'gfx90c',
                      'gfx1010', 'gfx1030', 'gfx1031']

# List of all supported CUDA toolkit versions supported by LLVM
CUDA_TOOLKIT_SUPPORT = ['80', '90', '91', '92', '100', '101', '102', '110', '111', '112']


# When extending the lists below, make sure to add additional sanity checks!
# List of the known LLVM projects
KNOWN_LLVM_PROJECTS = ['llvm', 'clang', 'polly', 'lld', 'lldb', 'clang-tools-extra', 'flang']
# List of the known LLVM runtimes
KNOWN_LLVM_RUNTIMES = ['compiler-rt', 'libunwind', 'libcxx', 'libcxxabi', 'openmp']


class EB_Clang(CMakeMake):
    """Support for bootstrapping Clang."""

    @staticmethod
    def extra_options():
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'amd_gfx_list': [None, "List of AMDGPU targets to build for. Possible values: " +
                             ', '.join(AMDGPU_GFX_SUPPORT), CUSTOM],
            'assertions': [True, "Enable assertions.  Helps to catch bugs in Clang.", CUSTOM],
            'bootstrap': [True, "Bootstrap Clang using GCC", CUSTOM],
            'build_extra_clang_tools': [False, "Build extra Clang tools", CUSTOM],
            'build_lld': [False, "Build the LLVM lld linker", CUSTOM],
            'build_lldb': [False, "Build the LLVM lldb debugger", CUSTOM],
            'build_targets': [None, "Build targets for LLVM (host architecture if None). Possible values: " +
                                    ', '.join(CLANG_TARGETS), CUSTOM],
            'default_cuda_capability': [None, "Default CUDA capability specified for clang, e.g. '7.5'", CUSTOM],
            'default_openmp_runtime': [None, "Default OpenMP runtime for clang (for example, 'libomp')", CUSTOM],
            'enable_rtti': [False, "Enable Clang RTTI", CUSTOM],
            'python_bindings': [False, "Install python bindings", CUSTOM],
            'libcxx': [False, "Build the LLVM C++ standard library", CUSTOM],
            'skip_all_tests': [False, "Skip running of tests", CUSTOM],
            'static_analyzer': [True, "Install the static analyser of Clang", CUSTOM],
            # The sanitizer tests often fail on HPC systems due to the 'weird' environment.
            'skip_sanitizer_tests': [True, "Do not run the sanitizer tests", CUSTOM],
            'usepolly': [False, "Build Clang with polly", CUSTOM],
            'llvm_projects': [[], "LLVM projects to install", CUSTOM],
            'llvm_runtimes': [[], "LLVM runtimes to install", CUSTOM],
        })
        # disable regular out-of-source build, too simplistic for Clang to work
        extra_vars['separate_build_dir'][0] = False
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize custom class variables for Clang."""

        super(EB_Clang, self).__init__(*args, **kwargs)
        self.llvm_src_dir = None
        self.llvm_obj_dir_stage1 = None
        self.llvm_obj_dir_stage2 = None
        self.llvm_obj_dir_stage3 = None
        self.make_parallel_opts = ""
        self.runtime_lib_path = "lib"

        if not self.cfg['llvm_projects']:
            self.cfg['llvm_projects'] = []
        if not self.cfg['llvm_runtimes']:
            self.cfg['llvm_runtimes'] = []

        # Be forgiving if someone places a runtime under projects since it is pretty new
        for project in [p for p in self.cfg['llvm_projects'] if p in KNOWN_LLVM_RUNTIMES]:
            msg = "LLVM project %s included but this should be a runtime, moving to runtime list!" % project
            self.log.warning(msg)
            self.cfg.update('llvm_runtimes', [project], allow_duplicate=False)
            # No cleaner way to remove an element from the list
            self.cfg['llvm_projects'] = [p for p in self.cfg['llvm_projects'] if p != project]
            print_warning(msg)

        for project in [p for p in self.cfg['llvm_projects'] if p not in KNOWN_LLVM_PROJECTS]:
            msg = "LLVM project %s included but not recognised, this project will NOT be sanity checked!" % project
            self.log.warning(msg)
            print_warning(msg)

        for runtime in [r for r in self.cfg['llvm_runtimes'] if r not in KNOWN_LLVM_RUNTIMES]:
            msg = "LLVM runtime %s included but not recognised, this runtime will NOT be sanity checked!" % runtime
            self.log.warning(msg)
            print_warning(msg)

        # keep compatibility between using llvm_projects/llvm_runtimes vs using flags
        if LooseVersion(self.version) >= LooseVersion('14'):
            self.cfg.update('llvm_projects', ['llvm', 'clang'], allow_duplicate=False)
            self.cfg.update('llvm_runtimes', ['compiler-rt', 'openmp'], allow_duplicate=False)
            if self.cfg['usepolly']:
                self.cfg.update('llvm_projects', 'polly', allow_duplicate=False)
            if self.cfg['build_lld']:
                self.cfg.update('llvm_projects', ['lld'], allow_duplicate=False)
                self.cfg.update('llvm_runtimes', ['libunwind'], allow_duplicate=False)
            if self.cfg['build_lldb']:
                self.cfg.update('llvm_projects', 'lldb', allow_duplicate=False)
            if self.cfg['libcxx']:
                self.cfg.update('llvm_runtimes', ['libcxx', 'libcxxabi'], allow_duplicate=False)
            if self.cfg['build_extra_clang_tools']:
                self.cfg.update('llvm_projects', 'clang-tools-extra', allow_duplicate=False)

        # ensure libunwind is there if lld is there
        if 'lld' in self.cfg['llvm_projects']:
            self.cfg.update('llvm_runtimes', 'libunwind', allow_duplicate=False)

        # ensure libcxxabi is there if libcxx is there
        if 'libcxx' in self.cfg['llvm_runtimes']:
            self.cfg.update('llvm_runtimes', 'libcxxabi', allow_duplicate=False)

        build_targets = self.cfg['build_targets']
        # define build_targets if not set
        if build_targets is None:
            deps = [dep['name'].lower() for dep in self.cfg.dependencies()]
            arch = get_cpu_architecture()
            try:
                default_targets = DEFAULT_TARGETS_MAP[arch][:]
                # If CUDA is included as a dep, add NVPTX as a target
                # There are (old) toolchains with CUDA as part of the toolchain
                cuda_toolchain = hasattr(self.toolchain, 'COMPILER_CUDA_FAMILY')
                if 'cuda' in deps or cuda_toolchain:
                    default_targets += ['NVPTX']
                # For AMDGPU support we need ROCR-Runtime and
                # ROCT-Thunk-Interface, however, since ROCT is a dependency of
                # ROCR we only check for the ROCR-Runtime here
                # https://openmp.llvm.org/SupportAndFAQ.html#q-how-to-build-an-openmp-amdgpu-offload-capable-compiler
                if 'rocr-runtime' in deps:
                    default_targets += ['AMDGPU']
                self.cfg['build_targets'] = build_targets = default_targets
                self.log.debug("Using %s as default build targets for CPU/GPU architecture %s.", default_targets, arch)
            except KeyError:
                raise EasyBuildError("No default build targets defined for CPU architecture %s.", arch)

        # carry on with empty list from this point forward if no build targets are specified
        if build_targets is None:
            self.cfg['build_targets'] = build_targets = []

        unknown_targets = [target for target in build_targets if target not in CLANG_TARGETS]

        if unknown_targets:
            raise EasyBuildError("Some of the chosen build targets (%s) are not in %s.",
                                 ', '.join(unknown_targets), ', '.join(CLANG_TARGETS))

        if LooseVersion(self.version) < LooseVersion('3.4') and "R600" in build_targets:
            raise EasyBuildError("Build target R600 not supported in < Clang-3.4")

        if LooseVersion(self.version) > LooseVersion('3.3') and "MBlaze" in build_targets:
            raise EasyBuildError("Build target MBlaze is not supported anymore in > Clang-3.3")

    def check_readiness_step(self):
        """Fail early on RHEL 5.x and derivatives because of known bug in libc."""
        super(EB_Clang, self).check_readiness_step()
        # RHEL 5.x have a buggy libc.  Building stage 2 will fail.
        if get_os_name() in ['redhat', 'RHEL', 'centos', 'SL'] and get_os_version().startswith('5.'):
            raise EasyBuildError("Can not build Clang on %s v5.x: libc is buggy, building stage 2 will fail. "
                                 "See http://stackoverflow.com/questions/7276828/", get_os_name())

    def extract_step(self):
        """
        Prepare a combined LLVM source tree.  The layout is different for versions earlier and later than 14.
        """

        # Extract everything into separate directories.
        super(EB_Clang, self).extract_step()

        # Find the full path to the directory that was unpacked from llvm-*.tar.gz.
        for tmp in self.src:
            if tmp['name'].startswith("llvm-"):
                self.llvm_src_dir = tmp['finalpath']
                break

        if self.llvm_src_dir is None:
            raise EasyBuildError("Could not determine LLVM source root (LLVM source was not unpacked?)")

        src_dirs = {}

        def find_source_dir(globpatterns, targetdir):
            """Search for directory with globpattern and rename it to targetdir"""
            if not isinstance(globpatterns, list):
                globpatterns = [globpatterns]

            glob_src_dirs = [glob_dir for globpattern in globpatterns for glob_dir in glob.glob(globpattern)]
            if len(glob_src_dirs) != 1:
                raise EasyBuildError("Failed to find exactly one source directory for pattern %s: %s", globpatterns,
                                     glob_src_dirs)
            src_dirs[glob_src_dirs[0]] = targetdir

        if any([x['name'].startswith('llvm-project') for x in self.src]):
            # if sources contain 'llvm-project*', we use the full tarball
            find_source_dir("../llvm-project-*", os.path.join(self.llvm_src_dir, "llvm-project-%s" % self.version))
            self.cfg.update('configopts', '-DLLVM_ENABLE_PROJECTS="%s"' % ';'.join(self.cfg['llvm_projects']))
            self.cfg.update('configopts', '-DLLVM_ENABLE_RUNTIMES="%s"' % ';'.join(self.cfg['llvm_runtimes']))
        else:
            # Layout for previous versions
            #        llvm/             Unpack llvm-*.tar.gz here
            #          projects/
            #            compiler-rt/  Unpack compiler-rt-*.tar.gz here
            #            openmp/       Unpack openmp-*.tar.xz here
            #          tools/
            #            clang/        Unpack clang-*.tar.gz here
            #              tools/
            #                extra/    Unpack clang-tools-extra-*.tar.gz here
            #            polly/        Unpack polly-*.tar.gz here
            #            libcxx/       Unpack libcxx-*.tar.gz here
            #            libcxxabi/    Unpack libcxxabi-*.tar.gz here
            #            lld/          Unpack lld-*.tar.gz here
            #            lldb/         Unpack lldb-*.tar.gz here
            #        libunwind/        Unpack libunwind-*.tar.gz here
            find_source_dir('compiler-rt-*', os.path.join(self.llvm_src_dir, 'projects', 'compiler-rt'))

            if 'polly' in self.cfg['llvm_projects']:
                find_source_dir('polly-*', os.path.join(self.llvm_src_dir, 'tools', 'polly'))

            if 'lld' in self.cfg['llvm_projects']:
                find_source_dir('lld-*', os.path.join(self.llvm_src_dir, 'tools', 'lld'))
                if LooseVersion(self.version) >= LooseVersion('12.0.1'):
                    find_source_dir('libunwind-*', os.path.normpath(os.path.join(self.llvm_src_dir, '..', 'libunwind')))

            if 'lldb' in self.cfg['llvm_projects']:
                find_source_dir('lldb-*', os.path.join(self.llvm_src_dir, 'tools', 'lldb'))

            if 'libcxx' in self.cfg['llvm_runtimes']:
                find_source_dir('libcxx-*', os.path.join(self.llvm_src_dir, 'projects', 'libcxx'))
                find_source_dir('libcxxabi-*', os.path.join(self.llvm_src_dir, 'projects', 'libcxxabi'))

            find_source_dir(['clang-[1-9]*', 'cfe-*'], os.path.join(self.llvm_src_dir, 'tools', 'clang'))

            if 'clang-tools-extra' in self.cfg['llvm_projects']:
                find_source_dir('clang-tools-extra-*',
                                os.path.join(self.llvm_src_dir, 'tools', 'clang', 'tools', 'extra'))

            if LooseVersion(self.version) >= LooseVersion('3.8'):
                find_source_dir('openmp-*', os.path.join(self.llvm_src_dir, 'projects', 'openmp'))

        for src in self.src:
            for (dirname, new_path) in src_dirs.items():
                if src['name'].startswith(dirname):
                    old_path = os.path.join(src['finalpath'], dirname)
                    try:
                        shutil.move(old_path, new_path)
                    except IOError as err:
                        raise EasyBuildError("Failed to move %s to %s: %s", old_path, new_path, err)
                    src['finalpath'] = new_path
                    break

    def configure_step(self):
        """Run CMake for stage 1 Clang."""

        if all(dep['name'] != 'ncurses' for dep in self.cfg['dependencies']):
            print_warning('Clang requires ncurses to run, did you forgot to add it to dependencies?')

        self.llvm_obj_dir_stage1 = os.path.join(self.builddir, 'llvm.obj.1')
        if self.cfg['bootstrap']:
            self.llvm_obj_dir_stage2 = os.path.join(self.builddir, 'llvm.obj.2')
            self.llvm_obj_dir_stage3 = os.path.join(self.builddir, 'llvm.obj.3')

        if LooseVersion(self.version) >= LooseVersion('3.3'):
            disable_san_tests = False
            # all sanitizer tests will fail when there's a limit on the vmem
            # this is ugly but I haven't found a cleaner way so far
            (vmemlim, ec) = run_cmd("ulimit -v", regexp=False)
            if not vmemlim.startswith("unlimited"):
                disable_san_tests = True
                self.log.warn("There is a virtual memory limit set of %s KB. The tests of the "
                              "sanitizers will be disabled as they need unlimited virtual "
                              "memory unless --strict=error is used." % vmemlim.strip())

            # the same goes for unlimited stacksize
            (stacklim, ec) = run_cmd("ulimit -s", regexp=False)
            if stacklim.startswith("unlimited"):
                disable_san_tests = True
                self.log.warn("The stacksize limit is set to unlimited. This causes the ThreadSanitizer "
                              "to fail. The sanitizers tests will be disabled unless --strict=error is used.")

            if (disable_san_tests or self.cfg['skip_sanitizer_tests']) and build_option('strict') != run.ERROR:
                self.log.debug("Disabling the sanitizer tests")
                self.disable_sanitizer_tests()

        # Create and enter build directory.
        mkdir(self.llvm_obj_dir_stage1)
        change_dir(self.llvm_obj_dir_stage1)

        # GCC and Clang are installed in different prefixes and Clang will not
        # find the GCC installation on its own.
        # First try with GCCcore, as GCC built on top of GCCcore is just a wrapper for GCCcore and binutils,
        # instead of a full-fledge compiler
        gcc_prefix = get_software_root('GCCcore')

        # If that doesn't work, try with GCC
        if gcc_prefix is None:
            gcc_prefix = get_software_root('GCC')

        # If that doesn't work either, print error and exit
        if gcc_prefix is None:
            raise EasyBuildError("Can't find GCC or GCCcore to use")

        self.cfg.update('configopts', "-DGCC_INSTALL_PREFIX='%s'" % gcc_prefix)
        self.log.debug("Using %s as GCC_INSTALL_PREFIX", gcc_prefix)

        # Configure some default options
        if self.cfg["enable_rtti"]:
            self.cfg.update('configopts', '-DLLVM_REQUIRES_RTTI=ON')
            self.cfg.update('configopts', '-DLLVM_ENABLE_RTTI=ON')
            self.cfg.update('configopts', '-DLLVM_ENABLE_EH=ON')
        if self.cfg["default_openmp_runtime"]:
            self.cfg.update(
                'configopts',
                '-DCLANG_DEFAULT_OPENMP_RUNTIME=%s' % self.cfg["default_openmp_runtime"]
            )

        if self.cfg['assertions']:
            self.cfg.update('configopts', "-DLLVM_ENABLE_ASSERTIONS=ON")
        else:
            self.cfg.update('configopts', "-DLLVM_ENABLE_ASSERTIONS=OFF")

        if 'polly' in self.cfg['llvm_projects']:
            # Not exactly sure when this change took place, educated guess
            if LooseVersion(self.version) >= LooseVersion('14'):
                self.cfg.update('configopts', "-DLLVM_POLLY_LINK_INTO_TOOLS=ON")
            else:
                self.cfg.update('configopts', "-DLINK_POLLY_INTO_TOOLS=ON")

        # If Z3 is included as a dep, enable support in static analyzer (if enabled)
        if self.cfg["static_analyzer"] and LooseVersion(self.version) >= LooseVersion('9.0.0'):
            z3_root = get_software_root("Z3")
            if z3_root:
                self.cfg.update('configopts', "-DLLVM_ENABLE_Z3_SOLVER=ON")
                self.cfg.update('configopts', "-DLLVM_Z3_INSTALL_DIR=%s" % z3_root)

        build_targets = self.cfg['build_targets']

        if 'polly' in self.cfg['llvm_projects'] and "NVPTX" in build_targets:
            self.cfg.update('configopts', "-DPOLLY_ENABLE_GPGPU_CODEGEN=ON")

        self.cfg.update('configopts', '-DLLVM_TARGETS_TO_BUILD="%s"' % ';'.join(build_targets))

        if self.cfg['parallel']:
            self.make_parallel_opts = "-j %s" % self.cfg['parallel']

        # If hwloc is included as a dep, use it in OpenMP runtime for affinity
        hwloc_root = get_software_root('hwloc')
        if hwloc_root:
            self.cfg.update('configopts', '-DLIBOMP_USE_HWLOC=ON')
            self.cfg.update('configopts', '-DLIBOMP_HWLOC_INSTALL_DIR=%s' % hwloc_root)

        # If 'NVPTX' is in the build targets we assume the user would like OpenMP offload support as well
        if 'NVPTX' in build_targets:
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
            self.cfg.update('configopts', '-DCLANG_OPENMP_NVPTX_DEFAULT_ARCH=sm_%s' % default_cc)
            self.cfg.update('configopts', '-DLIBOMPTARGET_NVPTX_COMPUTE_CAPABILITIES=%s' % ','.join(cuda_cc))
        # If we don't want to build with CUDA (not in dependencies) trick CMakes FindCUDA module into not finding it by
        # using the environment variable which is used as-is and later checked for a falsy value when determining
        # whether CUDA was found
        if not get_software_root('CUDA'):
            setvar('CUDA_NVCC_EXECUTABLE', 'IGNORE')
        # If 'AMDGPU' is in the build targets we assume the user would like OpenMP offload support for AMD
        if 'AMDGPU' in build_targets:
            if not get_software_root('ROCR-Runtime'):
                raise EasyBuildError("Can't build Clang with AMDGPU support "
                                     "without dependency 'ROCR-Runtime'")
            ec_amdgfx = self.cfg['amd_gfx_list']
            if not ec_amdgfx:
                raise EasyBuildError("Can't build Clang with AMDGPU support "
                                     "without specifying 'amd_gfx_list'")
            self.cfg.update('configopts', '-DLIBOMPTARGET_AMDGCN_GFXLIST=%s' % ' '.join(ec_amdgfx))

        self.log.info("Configuring")

        # directory structure has changed in version 14.x, cmake must start in llvm sub directory
        if LooseVersion(self.version) >= LooseVersion('14'):
            super(EB_Clang, self).configure_step(srcdir=os.path.join(self.llvm_src_dir, "llvm"))
        else:
            super(EB_Clang, self).configure_step(srcdir=self.llvm_src_dir)

    def disable_sanitizer_tests(self):
        """Disable the tests of all the sanitizers by removing the test directories from the build system"""
        if LooseVersion(self.version) < LooseVersion('3.6'):
            # for Clang 3.5 and lower, the tests are scattered over several CMakeLists.
            # We loop over them, and patch out the rule that adds the sanitizers tests to the testsuite
            patchfiles = ['lib/asan', 'lib/dfsan', 'lib/lsan', 'lib/msan', 'lib/tsan', 'lib/ubsan']

            for patchfile in patchfiles:
                cmakelists = os.path.join(self.llvm_src_dir, 'projects/compiler-rt', patchfile, 'CMakeLists.txt')
                if os.path.exists(cmakelists):
                    regex_subs = [(r'.*add_subdirectory\(lit_tests\).*', '')]
                    apply_regex_substitutions(cmakelists, regex_subs)

            # There is a common part seperate for the specific sanitizers, we disable all the common tests
            cmakelists = os.path.join('projects', 'compiler-rt', 'lib', 'sanitizer_common', 'CMakeLists.txt')
            regex_subs = [(r'.*add_subdirectory\(tests\).*', '')]
            apply_regex_substitutions(cmakelists, regex_subs)

        else:
            # In Clang 3.6, the sanitizer tests are grouped together in one CMakeLists
            # We patch out adding the subdirectories with the sanitizer tests
            if LooseVersion(self.version) >= LooseVersion('14'):
                cmakelists_tests = os.path.join(self.llvm_src_dir, 'compiler-rt', 'test', 'CMakeLists.txt')
            else:
                cmakelists_tests = os.path.join(self.llvm_src_dir, 'projects', 'compiler-rt', 'test', 'CMakeLists.txt')
            regex_subs = []
            if LooseVersion(self.version) >= LooseVersion('5.0'):
                regex_subs.append((r'compiler_rt_test_runtime.*san.*', ''))
            else:
                regex_subs.append((r'add_subdirectory\((.*san|sanitizer_common)\)', ''))

            apply_regex_substitutions(cmakelists_tests, regex_subs)

    def build_with_prev_stage(self, prev_obj, next_obj):
        """Build Clang stage N using Clang stage N-1"""

        # Create and enter build directory.
        mkdir(next_obj)
        change_dir(next_obj)

        # Make sure clang and clang++ compilers from the previous stage are (temporarily) in PATH
        # The call to prepare_rpath_wrappers() requires the compilers-to-be-wrapped on the PATH
        # Also, the call to 'which' in later in this current function also requires that
        orig_path = os.getenv('PATH')
        prev_obj_path = os.path.join(prev_obj, 'bin')
        setvar('PATH', prev_obj_path + ":" + orig_path)

        # If building with rpath, create RPATH wrappers for the Clang compilers for stage 2 and 3
        if build_option('rpath'):
            my_clang_toolchain = Clang(name='Clang', version='1')
            my_clang_toolchain.prepare_rpath_wrappers()
            self.log.info("Prepared clang rpath wrappers")

            # add symlink for 'opt' to wrapper dir, since Clang expects it in the same directory
            # see https://github.com/easybuilders/easybuild-easyblocks/issues/3075
            clang_wrapper_dir = os.path.dirname(which('clang'))
            symlink(os.path.join(prev_obj_path, 'opt'), os.path.join(clang_wrapper_dir, 'opt'))

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

        # determine full path to clang/clang++ (which may be wrapper scripts in case of RPATH linking)
        clang = which('clang')
        clangxx = which('clang++')

        # Configure.
        options = [
            "-DCMAKE_INSTALL_PREFIX=%s " % self.installdir,
            "-DCMAKE_C_COMPILER='%s' " % clang,
            "-DCMAKE_CXX_COMPILER='%s' " % clangxx,
            self.cfg['configopts'],
            "-DCMAKE_BUILD_TYPE=%s " % self.build_type,
        ]

        # Cmake looks for llvm-link by default in the same directory as the compiler
        # However, when compiling with rpath, the clang 'compiler' is not actually the compiler, but the wrapper
        # Clearly, the wrapper directory won't llvm-link. Thus, we pass the linker to be used by full path.
        # See https://github.com/easybuilders/easybuild-easyblocks/pull/2799#issuecomment-1275916186
        if build_option('rpath'):
            llvm_link = which('llvm-link')
            options.append("-DLIBOMPTARGET_NVPTX_BC_LINKER=%s" % llvm_link)

        self.log.info("Configuring")
        if LooseVersion(self.version) >= LooseVersion('14'):
            run_cmd("cmake %s %s" % (' '.join(options), os.path.join(self.llvm_src_dir, "llvm")), log_all=True)
        else:
            run_cmd("cmake %s %s" % (' '.join(options), self.llvm_src_dir), log_all=True)

        self.log.info("Building")
        run_cmd("make %s VERBOSE=1" % self.make_parallel_opts, log_all=True)

        # restore $PATH
        setvar('PATH', orig_path)

    def build_step(self):
        """Build Clang stage 1, 2, 3"""

        # Stage 1: build using system compiler.
        self.log.info("Building stage 1")
        change_dir(self.llvm_obj_dir_stage1)
        super(EB_Clang, self).build_step()

        if self.cfg['bootstrap']:
            self.log.info("Building stage 2")
            self.build_with_prev_stage(self.llvm_obj_dir_stage1, self.llvm_obj_dir_stage2)

            self.log.info("Building stage 3")
            self.build_with_prev_stage(self.llvm_obj_dir_stage2, self.llvm_obj_dir_stage3)

    def test_step(self):
        """Run Clang tests on final stage (unless disabled)."""
        if not self.cfg['skip_all_tests']:
            if self.cfg['bootstrap']:
                change_dir(self.llvm_obj_dir_stage3)
            else:
                change_dir(self.llvm_obj_dir_stage1)
            run_cmd("make %s check-all" % self.make_parallel_opts, log_all=True)

    def install_step(self):
        """Install stage 3 binaries."""

        if self.cfg['bootstrap']:
            change_dir(self.llvm_obj_dir_stage3)
        else:
            change_dir(self.llvm_obj_dir_stage1)
        super(EB_Clang, self).install_step()

        # the static analyzer is not installed by default
        # we do it by hand
        if self.cfg['static_analyzer'] and LooseVersion(self.version) < LooseVersion('3.8'):
            try:
                tools_src_dir = os.path.join(self.llvm_src_dir, 'tools', 'clang', 'tools')
                analyzer_target_dir = os.path.join(self.installdir, 'libexec', 'clang-analyzer')
                bindir = os.path.join(self.installdir, 'bin')
                for scan_dir in ['scan-build', 'scan-view']:
                    shutil.copytree(os.path.join(tools_src_dir, scan_dir), os.path.join(analyzer_target_dir, scan_dir))
                    os.symlink(os.path.relpath(bindir, os.path.join(analyzer_target_dir, scan_dir)),
                               os.path.join(analyzer_target_dir, scan_dir, 'bin'))
                    os.symlink(os.path.relpath(os.path.join(analyzer_target_dir, scan_dir, scan_dir), bindir),
                               os.path.join(bindir, scan_dir))

                mandir = os.path.join(self.installdir, 'share', 'man', 'man1')
                os.makedirs(mandir)
                shutil.copy2(os.path.join(tools_src_dir, 'scan-build', 'scan-build.1'), mandir)
            except OSError as err:
                raise EasyBuildError("Failed to copy static analyzer dirs to install dir: %s", err)

    def post_install_step(self):
        """Install python bindings."""
        super(EB_Clang, self).post_install_step()

        # copy Python bindings here in post-install step so that it is not done more than once in multi_deps context
        if self.cfg['python_bindings']:
            if LooseVersion(self.version) >= LooseVersion('14'):
                python_bindings_source_dir = os.path.join(self.llvm_src_dir, "clang", "bindings", "python")
            else:
                python_bindings_source_dir = os.path.join(self.llvm_src_dir, "tools", "clang", "bindings", "python")
            python_bindins_target_dir = os.path.join(self.installdir, 'lib', 'python')

            shutil.copytree(python_bindings_source_dir, python_bindins_target_dir)

    def sanity_check_step(self):
        """Custom sanity check for Clang."""
        custom_commands = ['clang --help', 'clang++ --help', 'llvm-config --cxxflags']
        shlib_ext = get_shared_lib_ext()

        version = LooseVersion(self.version)

        # Clang v16+ only use the major version number for the resource dir
        resdir_version = self.version
        if version >= '16':
            resdir_version = self.version.split('.')[0]

        # Detect OpenMP support for CPU architecture
        arch = get_cpu_architecture()
        # Check architecture explicitly since Clang uses potentially
        # different names
        if arch == X86_64:
            arch = 'x86_64'
        elif arch == POWER:
            arch = 'ppc64'
        elif arch == AARCH64:
            arch = 'aarch64'
        else:
            print_warning("Unknown CPU architecture (%s) for OpenMP and runtime libraries check!" % arch)

        if version >= '14':
            glob_pattern = os.path.join(self.installdir, 'lib', '%s-*' % arch)
            matches = glob.glob(glob_pattern)
            if matches:
                directory = os.path.basename(matches[0])
                self.runtime_lib_path = os.path.join("lib", directory)
            else:
                print_warning("Could not find runtime library directory")
                self.runtime_lib_path = "lib"
        else:
            self.runtime_lib_path = "lib"

        custom_paths = {
            'files': [
                "bin/clang", "bin/clang++", "bin/llvm-ar", "bin/llvm-nm", "bin/llvm-as", "bin/opt", "bin/llvm-link",
                "bin/llvm-config", "bin/llvm-symbolizer", "include/llvm-c/Core.h", "include/clang-c/Index.h",
                "lib/libclang.%s" % shlib_ext, "lib/clang/%s/include/stddef.h" % resdir_version,
            ],
            'dirs': ["include/clang", "include/llvm", "lib/clang/%s/lib" % resdir_version],
        }
        if self.cfg['static_analyzer']:
            custom_paths['files'].extend(["bin/scan-build", "bin/scan-view"])

        if 'clang-tools-extra' in self.cfg['llvm_projects'] and version >= '3.4':
            custom_paths['files'].extend(["bin/clang-tidy"])

        if 'polly' in self.cfg['llvm_projects']:
            custom_paths['files'].extend(["lib/LLVMPolly.%s" % shlib_ext])
            custom_paths['dirs'].extend(["include/polly"])

        if 'lld' in self.cfg['llvm_projects']:
            custom_paths['files'].extend(["bin/lld"])

        if 'lldb' in self.cfg['llvm_projects']:
            custom_paths['files'].extend(["bin/lldb"])

        if 'libunwind' in self.cfg['llvm_runtimes']:
            custom_paths['files'].extend([os.path.join(self.runtime_lib_path, "libunwind.%s" % shlib_ext)])

        if 'libcxx' in self.cfg['llvm_runtimes']:
            custom_paths['files'].extend([os.path.join(self.runtime_lib_path, "libc++.%s" % shlib_ext)])

        if 'libcxxabi' in self.cfg['llvm_runtimes']:
            custom_paths['files'].extend([os.path.join(self.runtime_lib_path, "libc++abi.%s" % shlib_ext)])

        if 'flang' in self.cfg['llvm_projects'] and version >= '15':
            flang_compiler = 'flang-new'
            custom_paths['files'].extend(["bin/%s" % flang_compiler])
            custom_commands.extend(["%s --help" % flang_compiler])

        if version >= '3.8':
            custom_paths['files'].extend(["lib/libomp.%s" % shlib_ext, "lib/clang/%s/include/omp.h" % resdir_version])

        if version >= '12':
            omp_target_libs = ["lib/libomptarget.%s" % shlib_ext, "lib/libomptarget.rtl.%s.%s" % (arch, shlib_ext)]
        else:
            omp_target_libs = ["lib/libomptarget.%s" % shlib_ext]
        custom_paths['files'].extend(omp_target_libs)

        # If building for CUDA check that OpenMP target library was created
        if 'NVPTX' in self.cfg['build_targets']:
            custom_paths['files'].append("lib/libomptarget.rtl.cuda.%s" % shlib_ext)
            # The static 'nvptx.a' library is not built from version 12 onwards
            if version < '12.0':
                custom_paths['files'].append("lib/libomptarget-nvptx.a")
            ec_cuda_cc = self.cfg['cuda_compute_capabilities']
            cfg_cuda_cc = build_option('cuda_compute_capabilities')
            cuda_cc = cfg_cuda_cc or ec_cuda_cc or []
            # We need the CUDA capability in the form of '75' and not '7.5'
            cuda_cc = [cc.replace('.', '') for cc in cuda_cc]
            if '12.0' < version < '13.0':
                custom_paths['files'].extend(["lib/libomptarget-nvptx-cuda_%s-sm_%s.bc" % (x, y)
                                             for x in CUDA_TOOLKIT_SUPPORT for y in cuda_cc])
            # libomptarget-nvptx-sm*.bc is not there for Clang 14.x;
            elif version < '14.0' or version >= '15.0':
                custom_paths['files'].extend(["lib/libomptarget-nvptx-sm_%s.bc" % cc
                                             for cc in cuda_cc])
            # From version 13, and hopefully onwards, the naming of the CUDA
            # '.bc' files became a bit simpler and now we don't need to take
            # into account the CUDA version Clang was compiled with, making it
            # easier to check for the bitcode files we expect;
            # libomptarget-new-nvptx-sm*.bc is only there in Clang 13.x and 14.x;
            if version >= '13.0' and version < '15.0':
                custom_paths['files'].extend(["lib/libomptarget-new-nvptx-sm_%s.bc" % cc
                                              for cc in cuda_cc])
        # If building for AMDGPU check that OpenMP target library was created
        if 'AMDGPU' in self.cfg['build_targets']:
            custom_paths['files'].append("lib/libLLVMAMDGPUCodeGen.a")
            # OpenMP offloading support to AMDGPU was not added until version
            # 13, however, building for the AMDGPU target predates this and so
            # doesn't necessarily mean that the AMDGPU target failed
            if version >= '13.0':
                custom_paths['files'].append("lib/libomptarget.rtl.amdgpu.%s" % shlib_ext)
                custom_paths['files'].extend(["lib/libomptarget-amdgcn-%s.bc" % gfx
                                              for gfx in self.cfg['amd_gfx_list']])
                custom_paths['files'].append("bin/amdgpu-arch")
            if version >= '14.0':
                custom_paths['files'].extend(["lib/libomptarget-new-amdgpu-%s.bc" % gfx
                                              for gfx in self.cfg['amd_gfx_list']])

        if self.cfg['python_bindings']:
            custom_paths['files'].extend([os.path.join("lib", "python", "clang", "cindex.py")])
            custom_commands.extend(["python -s -c 'import clang'"])

        super(EB_Clang, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """Custom variables for Clang module."""
        txt = super(EB_Clang, self).make_module_extra()
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
        guesses = super(EB_Clang, self).make_module_req_guess()
        guesses.update({
            'CPATH': [],
            'LIBRARY_PATH': [],
            'LD_LIBRARY_PATH': ['lib', 'lib64', self.runtime_lib_path],
        })
        return guesses
