##
# Copyright 2009-2020 Ghent University
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
from distutils.version import LooseVersion
import glob
import os

import easybuild.tools.environment as env
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions, copy_file, which
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.framework.easyconfig import CUSTOM


class EB_Bazel(EasyBlock):
    """Support for building/installing Bazel."""

    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to EB_Bazel."""
        extra_vars = dict(ConfigureMake.extra_options(extra_vars))
        extra_vars.update({
            'static': [False, "Build statically linked executables", CUSTOM],
        })
        return EasyBlock.extra_options(extra_vars)

    def fixup_hardcoded_paths(self):
        """Patch out hard coded paths to compiler and binutils tools"""
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

    def configure_step(self):
        """Custom configuration procedure for Bazel."""

        # Last instance of hardcoded paths was removed in 0.24.0
        if LooseVersion(self.version) < LooseVersion('0.24.0'):
            self.fixup_hardcoded_paths()

        # enable building in parallel
        bazel_args = '--jobs=%d' % self.cfg['parallel']

        # Bazel provides a JDK by itself for some architectures
        # We want to enforce it using the JDK we provided via modules
        # This is required for Power where Bazel does not have a JDK, but requires it for building itself
        # See https://github.com/bazelbuild/bazel/issues/10377
        bazel_args += ' --host_javabase=@local_jdk//:jdk'

        env.setvar('EXTRA_BAZEL_ARGS', bazel_args)

    def build_step(self):
        """Custom build procedure for Bazel."""
        static = ''
        if self.cfg['static'] is True:
            static = 'export BAZEL_LINKOPTS=-static-libstdc++:-static-libgcc BAZEL_LINKLIBS=-l%:libstdc++.a:-lm && '

        cmd = '%s %s ./compile.sh' % (static, self.cfg['prebuildopts'])
        run_cmd(cmd, log_all=True, simple=True, log_ok=True)

    def install_step(self):
        """Custom install procedure for Bazel."""
        copy_file(os.path.join('output', 'bazel'), os.path.join(self.installdir, 'bin', 'bazel'))

    def sanity_check_step(self):
        """Custom sanity check for Bazel."""
        custom_paths = {
            'files': ['bin/bazel'],
            'dirs': [],
        }
        super(EB_Bazel, self).sanity_check_step(custom_paths=custom_paths)
