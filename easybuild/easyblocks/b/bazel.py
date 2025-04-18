##
# Copyright 2009-2025 Ghent University
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
EasyBuild support for building and installing Bazel, implemented as an easyblock
"""
from easybuild.tools import LooseVersion
import glob
import os
import tempfile

import easybuild.tools.environment as env
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions, copy_file, which
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd
from easybuild.framework.easyconfig import CUSTOM


class EB_Bazel(EasyBlock):
    """Support for building/installing Bazel."""

    @staticmethod
    def extra_options():
        """Extra easyconfig parameters specific to EB_Bazel."""
        extra_vars = {
            'static': [None, 'Build statically linked executables ' +
                             '(default: True for Bazel >= 1.0 else False)', CUSTOM],
        }
        return EasyBlock.extra_options(extra_vars)

    def fixup_hardcoded_paths(self):
        """Patch out hard coded paths to /tmp, compiler and binutils tools"""
        # replace hardcoded /tmp in java build scripts
        regex_subs = [
            (r'`mktemp -d /tmp/tmp.XXXXXXXXXX`', '$$(mktemp -d $${TMPDIR:-/tmp}/tmp.XXXXXXXXXX)'),
        ]
        filepath = os.path.join('src', 'main', 'java', 'com', 'google', 'devtools', 'build', 'lib', 'BUILD')
        if os.path.exists(filepath):
            apply_regex_substitutions(filepath, regex_subs)

        binutils_root = get_software_root('binutils')
        gcc_root = get_software_root('GCCcore') or get_software_root('GCC')
        gcc_ver = get_software_version('GCCcore') or get_software_version('GCC')

        # only patch Bazel scripts if binutils & GCC installation prefix could be determined
        if not binutils_root or not gcc_root:
            self.log.info("Not patching Bazel build scripts, installation prefix for binutils/GCC not found")
            return

        # replace hardcoded paths in (unix_)cc_configure.bzl
        # hard-coded paths in (unix_)cc_configure.bzl were removed in 0.19.0
        if LooseVersion(self.version) < LooseVersion('0.19.0'):
            regex_subs = [
                (r'-B/usr/bin', '-B%s' % os.path.join(binutils_root, 'bin')),
                (r'"/usr/bin', '"' + os.path.join(binutils_root, 'bin')),
            ]
            for conf_bzl in ['cc_configure.bzl', 'unix_cc_configure.bzl']:
                filepath = os.path.join('tools', 'cpp', conf_bzl)
                if os.path.exists(filepath):
                    apply_regex_substitutions(filepath, regex_subs)

        # replace hardcoded paths in CROSSTOOL
        # CROSSTOOL script is no longer there in Bazel 0.24.0
        if LooseVersion(self.version) < LooseVersion('0.24.0'):
            res = glob.glob(os.path.join(gcc_root, 'lib', 'gcc', '*', gcc_ver, 'include'))
            if res and len(res) == 1:
                gcc_lib_inc = res[0]
            else:
                raise EasyBuildError("Failed to pinpoint location of GCC include files: %s", res)

            gcc_lib_inc_bis = os.path.join(os.path.dirname(gcc_lib_inc), 'include-fixed')
            if not os.path.exists(gcc_lib_inc_bis):
                self.log.info("Derived directory %s does not exist, falling back to %s", gcc_lib_inc_bis, gcc_lib_inc)
                gcc_lib_inc_bis = gcc_lib_inc

            gcc_cplusplus_inc = os.path.join(gcc_root, 'include', 'c++', gcc_ver)
            if not os.path.exists(gcc_cplusplus_inc):
                raise EasyBuildError("Derived directory %s does not exist", gcc_cplusplus_inc)

            regex_subs = [
                (r'-B/usr/bin', '-B%s' % os.path.join(binutils_root, 'bin')),
                (r'(cxx_builtin_include_directory:.*)/usr/lib/gcc', r'\1%s' % gcc_lib_inc),
                (r'(cxx_builtin_include_directory:.*)/usr/local/include', r'\1%s' % gcc_lib_inc_bis),
                (r'(cxx_builtin_include_directory:.*)/usr/include', r'\1%s' % gcc_cplusplus_inc),
            ]
            for tool in ['ar', 'cpp', 'dwp', 'gcc', 'ld']:
                path = which(tool)
                if path:
                    regex_subs.append((os.path.join('/usr', 'bin', tool), path))
                else:
                    raise EasyBuildError("Failed to determine path to '%s'", tool)

            apply_regex_substitutions(os.path.join('tools', 'cpp', 'CROSSTOOL'), regex_subs)

    def prepare_step(self, *args, **kwargs):
        """Setup bazel output root"""
        super(EB_Bazel, self).prepare_step(*args, **kwargs)
        self.bazel_tmp_dir = tempfile.mkdtemp(suffix='-bazel-tmp', dir=self.builddir)
        self._make_output_user_root()

    def _make_output_user_root(self):
        if not os.path.isdir(self.builddir):
            # Can happen on module-only or sanity-check-only runs
            self.log.info("Using temporary folder for user_root as builddir doesn't exist")
            dir = None  # Will use the EB created temp dir
        else:
            dir = self.builddir
        self._output_user_root = tempfile.mkdtemp(suffix='-bazel-root', dir=dir)

    @property
    def output_user_root(self):
        try:
            return self._output_user_root
        except AttributeError:
            self._make_output_user_root()
            return self._output_user_root

    def extract_step(self):
        """Extract Bazel sources."""
        # Older Bazel won't build when the output_user_root is a subfolder of the source folder
        # So create a dedicated source folder
        self.cfg.update('unpack_options', '-d src')
        super(EB_Bazel, self).extract_step()

    def configure_step(self):
        """Custom configuration procedure for Bazel."""

        # Last instance of hardcoded compiler/binutils paths was removed in 0.24.0, however
        # hardcoded /tmp affects all versions
        self.fixup_hardcoded_paths()

        # Keep temporary directory in case of error. EB will clean it up on success
        apply_regex_substitutions(os.path.join('scripts', 'bootstrap', 'buildenv.sh'), [
            (r'atexit cleanup_tempdir_.*', '')
        ])

        # enable building in parallel
        bazel_args = f'--jobs={self.cfg.parallel}'

        # Bazel provides a JDK by itself for some architectures
        # We want to enforce it using the JDK we provided via modules
        # This is required for Power where Bazel does not have a JDK, but requires it for building itself
        # See https://github.com/bazelbuild/bazel/issues/10377
        if LooseVersion(self.version) >= LooseVersion('7.0'):
            # Option changed in Bazel 7.x, see https://github.com/bazelbuild/bazel/issues/22789
            bazel_args += ' --tool_java_runtime_version=local_jdk'
        else:
            bazel_args += ' --host_javabase=@local_jdk//:jdk'

        # Link C++ libs statically, see https://github.com/bazelbuild/bazel/issues/4137
        static = self.cfg['static']
        if static is None:
            # Works for Bazel 1.x and higher
            static = LooseVersion(self.version) >= LooseVersion('1.0.0')
        if static:
            env.setvar('BAZEL_LINKOPTS', '-static-libstdc++:-static-libgcc')
            env.setvar('BAZEL_LINKLIBS', '-l%:libstdc++.a')

        env.setvar('EXTRA_BAZEL_ARGS', bazel_args)
        env.setvar('EMBED_LABEL', self.version)
        env.setvar('VERBOSE', 'yes')

    def build_step(self):
        """Custom build procedure for Bazel."""
        cmd = ' '.join([
            "export TMPDIR='%s' &&" % self.bazel_tmp_dir,  # The initial bootstrap of bazel is done in TMPDIR
            self.cfg['prebuildopts'],
            "bash -c 'set -x && ./compile.sh'",  # Show the commands the script is running to faster debug failures
        ])
        run_shell_cmd(cmd)

    def test_step(self):
        """Test the compilation"""

        runtest = self.cfg['runtest']
        if runtest:
            # This could be used to pass options to Bazel: runtest = '--bazel-opt=foo test'
            if runtest is True:
                runtest = 'test'
            cmd = " ".join([
                self.cfg['pretestopts'],
                os.path.join('output', 'bazel'),
                # Avoid bazel using $HOME
                '--output_user_root=%s' % self.output_user_root,
                runtest,
                f'--jobs={self.cfg.parallel}',
                '--host_javabase=@local_jdk//:jdk',
                # Be more verbose
                '--subcommands', '--verbose_failures',
                # Just build tests
                '--build_tests_only',
                self.cfg['testopts']
            ])
            run_shell_cmd(cmd)

    def install_step(self):
        """Custom install procedure for Bazel."""
        copy_file(os.path.join('output', 'bazel'), os.path.join(self.installdir, 'bin', 'bazel'))

    def sanity_check_step(self):
        """Custom sanity check for Bazel."""
        custom_paths = {
            'files': ['bin/bazel'],
            'dirs': [],
        }
        custom_commands = []
        if LooseVersion(self.version) >= LooseVersion('1.0'):
            # Avoid writes to $HOME
            custom_commands.append("bazel --output_user_root=%s --help" % self.output_user_root)

        super(EB_Bazel, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
