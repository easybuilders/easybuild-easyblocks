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
import shutil

from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion, run
from easybuild.tools.build_log import EasyBuildError, print_msg, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.environment import setvar
from easybuild.tools.filetools import (apply_regex_substitutions, change_dir,
                                       mkdir)
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import (get_cpu_architecture,
                                         get_shared_lib_ext)

from easybuild.easyblocks.clang import CLANG_TARGETS, DEFAULT_TARGETS_MAP
from easybuild.easyblocks.generic.cmakemake import CMakeMake

cmake_opt_post3 = {
    'LIBCXX_CXX_ABI': 'libcxxabi',
    'LIBCXX_USE_COMPILER_RT': 'On',
    'LIBCXXABI_USE_LLVM_UNWINDER': 'On',
    'LIBCXXABI_USE_COMPILER_RT': 'On',
    'LIBCXX_HAS_GCC_S_LIB': 'Off',
    'LIBUNWIND_USE_COMPILER_RT': 'On',
    'CLANG_DEFAULT_CXX_STDLIB': 'libc++',
    'CLANG_DEFAULT_RTLIB': 'compiler-rt',
    'CLANG_DEFAULT_LINKER': 'lld',
    'LLVM_POLLY_LINK_INTO_TOOLS': 'ON',
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
            'bootstrap': [True, "Build LLVM using itself", CUSTOM],
            'enable_rtti': [True, "Enable RTTI", CUSTOM],
            'skip_all_tests': [False, "Skip running of tests", CUSTOM],
            'skip_sanitizer_tests': [True, "Do not run the sanitizer tests", CUSTOM],
            'python_bindings': [False, "Install python bindings", CUSTOM],
            'test_suite_max_failed': [0, "Maximum number of failing tests (does not count allowed failures)", CUSTOM],
        })

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize LLVM-specific variables."""
        super(EB_LLVMcore, self).__init__(*args, **kwargs)
        self.llvm_src_dir = None
        self.llvm_obj_dir_stage1 = None
        self.llvm_obj_dir_stage2 = None
        self.llvm_obj_dir_stage3 = None
        # self.llvm_obj_dir_stage4 = None
        self.make_parallel_opts = ""

        if LooseVersion(self.version) < LooseVersion('18.1.6'):
            raise EasyBuildError("LLVM version %s is not supported, please use version 18.1.6 or newer", self.version)

        self.build_shared = self.cfg.get('build_shared_libs', False)
        # self.cfg['start_dir'] = 'llvm'
        if self.build_shared:
            self.cfg['build_shared_libs'] = None

        # self._projects = ['llvm']
        # self._runtimes = ['compiler-rt', 'libunwind', 'libcxx', 'libcxxabi']
        self._cmakeopts = {
            'LLVM_ENABLE_PROJECTS': 'llvm;lld;lldb;polly;mlir',
            'LLVM_ENABLE_RUNTIMES': 'compiler-rt;libunwind;libcxx;libcxxabi',
        }
        self.llvm_src_dir = os.path.join(self.builddir, 'llvm-project-%s.src' % self.version)

    def _general_configure_step(self):
        """General configuration step for LLVM."""
        self._cmakeopts['CMAKE_BUILD_TYPE'] = self.build_type
        # If EB is launched from a venv, avoid giving priority to the venv's python
        self._cmakeopts['Python3_FIND_VIRTUALENV'] = 'STANDARD'
        self._cmakeopts['LLVM_INSTALL_UTILS'] = 'ON'
        self._cmakeopts['LLVM_INCLUDE_BENCHMARKS'] = 'OFF'
        self._cmakeopts['LLVM_ENABLE_ASSERTIONS'] = 'ON' if self.cfg['assertions'] else 'OFF'

        if self.build_shared:
            self.cfg.update('configopts', '-DLLVM_BUILD_LLVM_DYLIB=ON -DLLVM_LINK_LLVM_DYLIB=ON')

        if get_software_root('zlib'):
            self._cmakeopts['LLVM_ENABLE_ZLIB'] = 'ON'

        if self.cfg["enable_rtti"]:
            self._cmakeopts['LLVM_REQUIRES_RTTI'] = 'ON'
            self._cmakeopts['LLVM_ENABLE_RTTI'] = 'ON'
            # self._cmakeopts['LLVM_ENABLE_EH'] = 'ON'

    def configure_step(self):
        """
        Install extra tools in bin/; enable zlib if it is a dep; optionally enable rtti; and set the build target
        """
        gcc_version = get_software_version('GCCcore')
        if LooseVersion(gcc_version) < LooseVersion('13'):
            raise EasyBuildError("LLVM %s requires GCC 13 or newer, found %s", self.version, gcc_version)

        if self.cfg['parallel']:
            self.make_parallel_opts = "-j %s" % self.cfg['parallel']

        self.llvm_obj_dir_stage1 = os.path.join(self.builddir, 'llvm.obj.1')
        if self.cfg['bootstrap']:
            self.log.info("Initialising for bootstrap build.")
            self.llvm_obj_dir_stage2 = os.path.join(self.builddir, 'llvm.obj.2')
            self.llvm_obj_dir_stage3 = os.path.join(self.builddir, 'llvm.obj.3')
            # self.llvm_obj_dir_stage4 = os.path.join(self.builddir, 'llvm.obj.4')
            mkdir(self.llvm_obj_dir_stage2)
            mkdir(self.llvm_obj_dir_stage3)
            # mkdir(self.llvm_obj_dir_stage4)
            self._cmakeopts['LLVM_ENABLE_PROJECTS'] = '"llvm;lld;clang"'
            self._cmakeopts['LLVM_ENABLE_RUNTIMES'] = '"compiler-rt;libunwind;libcxx;libcxxabi"'

        if self.cfg['skip_sanitizer_tests'] and build_option('strict') != run.ERROR:
            self.log.debug("Disabling the sanitizer tests")
            self.disable_sanitizer_tests()

        gcc_prefix = get_software_root('GCCcore')
        # If that doesn't work, try with GCC
        if gcc_prefix is None:
            gcc_prefix = get_software_root('GCC')
        # If that doesn't work either, print error and exit
        if gcc_prefix is None:
            raise EasyBuildError("Can't find GCC or GCCcore to use")
        self._cmakeopts['GCC_INSTALL_PREFIX'] = gcc_prefix
        self.log.debug("Using %s as GCC_INSTALL_PREFIX", gcc_prefix)

        self._general_configure_step()

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

        self.cfg.update('configopts', '-DLLVM_TARGETS_TO_BUILD="%s"' % ';'.join(build_targets))

        self._cfgopts = list(filter(None, self.cfg.get('configopts', '').split()))

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
        for k,v in self._cmakeopts.items():
            base_opts.append('-D%s=%s' % (k, v))
        self.cfg['configopts'] = ' '.join(base_opts)

        self.log.debug("-%"*50)
        self.log.debug("Using %s as configopts", self._cfgopts)
        self.log.debug("Using %s as cmakeopts", self._cmakeopts)
        self.log.debug("-%"*50)

    def configure_step2(self):
        """Configure the second stage of the bootstrap."""
        self._cmakeopts = {}
        self._general_configure_step()
        self._cmakeopts['LLVM_ENABLE_PROJECTS'] = '"llvm;lld;clang"'
        self._cmakeopts['LLVM_ENABLE_RUNTIMES'] = '"compiler-rt;libunwind;libcxx;libcxxabi"'

    # def configure_step3(self):
    #     """Configure the second stage of the bootstrap."""
    #     self._cmakeopts = {}
    #     self._general_configure_step()
    #     self._cmakeopts['LLVM_ENABLE_PROJECTS'] = '"llvm;lld;clang"'
    #     self._cmakeopts['LLVM_ENABLE_RUNTIMES'] = '"compiler-rt;libunwind;libcxx;libcxxabi"'
    #     self._cmakeopts.update(cmake_opt_post3)

    def configure_step3(self):
        """Configure the third stage of the bootstrap."""
        self._cmakeopts = {}
        self._general_configure_step()
        self._cmakeopts['LLVM_ENABLE_PROJECTS'] = '"llvm;lld;lldb;mlir;polly;clang;flang"'
        self._cmakeopts['LLVM_ENABLE_RUNTIMES'] = '"compiler-rt;libunwind;libcxx;libcxxabi"'
        self._cmakeopts.update(cmake_opt_post3)

    def build_with_prev_stage(self, prev_dir, stage_dir):
        """Build LLVM using the previous stage."""
        curdir = os.getcwd()
        orig_path = os.getenv('PATH')
        orig_library_path = os.getenv('LIBRARY_PATH')
        orig_ld_library_path = os.getenv('LD_LIBRARY_PATH')

        self._cmakeopts['CMAKE_C_COMPILER'] = os.path.join(prev_dir, 'bin/clang')
        self._cmakeopts['CMAKE_CXX_COMPILER'] = os.path.join(prev_dir, 'bin/clang++')
        # self._cmakeopts['CMAKE_ASM_COMPILER'] = os.path.join(prev_dir, 'bin/clang')

        self.add_cmake_opts()

        bin_dir = os.path.join(prev_dir, 'bin')
        prev_lib_dir = os.path.join(prev_dir, 'lib')
        curr_lib_dir = os.path.join(stage_dir, 'lib')
        lib_dir_runtime = self.get_runtime_lib_path(prev_dir, fail_ok=False)

        # Give priority to the libraries in the current stage if compiled to avoid failures due to undefined symbols
        # e.g. when calling the compiled clang-ast-dump for stage 3
        lib_path = ':'.join([
            curr_lib_dir,
            os.path.join(curr_lib_dir, lib_dir_runtime),
            prev_lib_dir,
            os.path.join(prev_dir, lib_dir_runtime),
        ])

        # setvar('PATH', bin_dir + ":" + orig_path)
        # setvar('LIBRARY_PATH', lib_path + ":" + orig_library_path)
        # setvar('LD_LIBRARY_PATH', lib_path + ":" + orig_ld_library_path)

        self.cfg.update('preconfigopts', ' '.join([
            'PATH=%s:%s' % (bin_dir, orig_path),
            'LIBRARY_PATH=%s:%s' % (lib_path, orig_library_path),
            'LD_LIBRARY_PATH=%s:%s' % (lib_path, orig_ld_library_path)
        ]))
        super(EB_LLVMcore, self).configure_step(
            builddir=stage_dir,
            srcdir=os.path.join(self.llvm_src_dir, "llvm")
            )

        # change_dir(stage_dir)
        # self.log.debug("Configuring %s", stage_dir)
        # cmd = "cmake %s %s" % (self.cfg['configopts'], os.path.join(self.llvm_src_dir, 'llvm'))
        # run_cmd(cmd, log_all=True)
        self.log.debug("Building %s", stage_dir)
        cmd = "make %s VERBOSE=1" % self.make_parallel_opts
        run_cmd(cmd, log_all=True)

        change_dir(curdir)
        # setvar('PATH', orig_path)
        # setvar('LIBRARY_PATH', orig_library_path)
        # setvar('LD_LIBRARY_PATH', orig_ld_library_path)

    def build_step(self, verbose=False, path=None):
        """Build LLVM, and optionally build it using itself."""
        self.log.info("Building stage 1")
        print_msg("Building stage 1")
        # change_dir(self.llvm_obj_dir_stage1)
        # super(EB_LLVMcore, self).build_step(verbose, path)
        change_dir(self.builddir)
        shutil.rmtree('llvm.obj.1', ignore_errors=True)
        shutil.copytree(os.path.join('..', 'llvm.obj.1'), 'llvm.obj.1')
        if self.cfg['bootstrap']:
            self.log.info("Building stage 2")
            print_msg("Building stage 2")
            # self.configure_step2()
            # self.build_with_prev_stage(self.llvm_obj_dir_stage1, self.llvm_obj_dir_stage2)
            change_dir(self.builddir)
            shutil.rmtree('llvm.obj.2', ignore_errors=True)
            shutil.copytree(os.path.join('..', 'llvm.obj.2'), 'llvm.obj.2')

            self.log.info("Building stage 3")
            print_msg("Building stage 3")
            self.configure_step3()
            self.build_with_prev_stage(self.llvm_obj_dir_stage2, self.llvm_obj_dir_stage3)
            # change_dir(self.builddir)
            # shutil.rmtree('llvm.obj.3', ignore_errors=True)
            # shutil.copytree(os.path.join('..', 'llvm.obj.3'), 'llvm.obj.3')

            # self.log.info("Building stage 4")
            # print_msg("Building stage 4")
            # self.configure_step4()
            # self.build_with_prev_stage(self.llvm_obj_dir_stage3, self.llvm_obj_dir_stage4)
            # # change_dir(self.builddir)
            # # shutil.rmtree('llvm.obj.3', ignore_errors=True)
            # # shutil.copytree(os.path.join('..', 'llvm.obj.3'), 'llvm.obj.3')

    def test_step(self):
        """Run Clang tests on final stage (unless disabled)."""
        if not self.cfg['skip_all_tests']:
            if self.cfg['bootstrap']:
                basedir = self.llvm_obj_dir_stage3
            else:
                basedir = self.llvm_obj_dir_stage1

            change_dir(basedir)
            orig_path = os.getenv('PATH')
            orig_ld_library_path = os.getenv('LD_LIBRARY_PATH')
            lib_dir = os.path.join(basedir, 'lib')
            lib_dir_runtime = self.get_runtime_lib_path(basedir, fail_ok=False)
            lib_path = ':'.join([lib_dir, os.path.join(basedir, lib_dir_runtime), orig_ld_library_path])
            setvar('PATH', os.path.join(basedir, 'bin') + ":" + orig_path)
            setvar('LD_LIBRARY_PATH', lib_path)

            cmd = "make %s check-all" % self.make_parallel_opts
            (out, _) = run_cmd(cmd, log_all=False, log_ok=False, simple=False, regexp=False)

            setvar('PATH', orig_path)
            setvar('LD_LIBRARY_PATH', orig_ld_library_path)

            rgx = re.compile(r'^ +Failed +: +([0-9]+)', flags=re.MULTILINE)
            mch = rgx.search(out)
            if mch is None:
                raise EasyBuildError("Failed to extract number of failed tests from output: %s", out)
            num_failed = int(mch.group(1))
            if num_failed > self.cfg['test_suite_max_failed']:
                raise EasyBuildError("Too many failed tests: %s", num_failed)


    def install_step(self):
        """Install stage 1 or 3 (if bootsrap) binaries."""
        if self.cfg['bootstrap']:
            change_dir(self.llvm_obj_dir_stage3)
        else:
            change_dir(self.llvm_obj_dir_stage1)
        super(EB_LLVMcore, self).install_step()

    def get_runtime_lib_path(self, base_dir, fail_ok=True):
        """Return the path to the runtime libraries."""
        arch = get_cpu_architecture()
        glob_pattern = os.path.join(base_dir, 'lib', '%s-*' % arch)
        matches = glob.glob(glob_pattern)
        if matches:
            directory = os.path.basename(matches[0])
            res =  os.path.join("lib", directory)
        else:
            if not fail_ok:
                raise EasyBuildError("Could not find runtime library directory")
            print_warning("Could not find runtime library directory")
            res = "lib"

        return res

    def sanity_check_step(self, custom_paths=None, custom_commands=None, extension=False, extra_modules=None):
        self.runtime_lib_path = self.get_runtime_lib_path(self.installdir, fail_ok=False)
        shlib_ext = get_shared_lib_ext()

        if self.cfg['build_shared_libs']:
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
        guesses = super(EB_LLVMcore, self).make_module_req_guess()
        guesses.update({
            'CPATH': [],
            'LIBRARY_PATH': ['lib', 'lib64', self.runtime_lib_path],
            'LD_LIBRARY_PATH': ['lib', 'lib64', self.runtime_lib_path],
        })
        return guesses
