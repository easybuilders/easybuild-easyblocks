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
EasyBuild support for building and installing deepmind/reverb, implemented as an easyblock
@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import os

from easybuild.easyblocks.generic.pythonpackage import PythonPackage, PIP_INSTALL_CMD
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.environment import setvar
from easybuild.tools.filetools import mkdir, remove_dir
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd


class EB_dm_minus_reverb(PythonPackage):
    """Support for installing deepmind/reverb Python package."""

    def configure_step(self, *args, **kwargs):
        """Execute custom configure.py script"""
        super(EB_dm_minus_reverb, self).configure_step(*args, **kwargs)

        # set Python environment
        python_root = get_software_root('Python')
        if python_root:
            pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
            pylibdir = os.path.join(self.installdir, 'lib', 'python%s' % pyshortver, 'site-packages')
            setvar('PYTHON_LIB_PATH', pylibdir)
            pybin = os.path.join(python_root, 'bin', 'python')
            setvar('PYTHON_BIN_PATH', pybin)
        else:
            raise EasyBuildError("Python not found in dependency list.")

        # use protobuf version from EB
        if get_software_root('protobuf'):
            setvar('REVERB_PROTOC_VERSION', get_software_version('protobuf'))

        # execute custom configuration script
        conf_cmd = "python configure.py"
        res = run_shell_cmd(conf_cmd)
        return res.exit_code

    def build_step(self, *args, **kwargs):
        """Build with Bazel"""
        if not get_software_root('Bazel'):
            raise EasyBuildError("Bazel not found in dependency list.")

        # separate build dir for Bazel
        build_dir = os.path.join(self.builddir, 'easybuild_obj')
        if os.path.exists(build_dir):
            self.log.warning('Build directory %s already exists (from previous iterations?). Removing...', build_dir)
            remove_dir(build_dir)
        mkdir(build_dir, parents=True)
        bazel_opts = "--output_user_root %s" % build_dir

        # build target
        bazel_build_pkg = '//reverb/pip_package:build_pip_package'

        # generate build command
        bazel_build_opts = self.cfg['buildopts']
        # by default generate a release build
        if not all(opt in bazel_build_opts for opt in (" --compilation_mode", " -c")):
            bazel_build_opts += " --compilation_mode=opt"
        # set C++ standard (--cxxopt can be used multiple times)
        cstd = self.toolchain.options.get('cstd', None)
        if cstd:
            bazel_build_opts += " --cxxopt='-std=%s'" % cstd
        # use JDK from EB
        bazel_build_opts += " --host_javabase=@local_jdk//:jdk"
        # explicitly set the number of processes
        bazel_build_opts += f" --jobs={self.cfg.parallel}"
        # print full compilation commands
        bazel_build_opts += " --subcommands"

        bazel_cmd = "%s bazel %s build %s %s" % (self.cfg['prebuildopts'], bazel_opts, bazel_build_opts,
                                                 bazel_build_pkg)

        res = run_shell_cmd(bazel_cmd)
        return res.exit_code

    def install_step(self, *args, **kwargs):
        """Package deepmind/reverb in a wheel and install it with pip"""

        # package a release version
        whl_build_opts = "--release"
        whl_build_opts += " --dst %s/" % self.builddir
        # target TF from EasyBuild
        if get_software_root('TensorFlow'):
            whl_build_opts += " --tf-version %s" % get_software_version('TensorFlow')

        whl_cmd = "./bazel-bin/reverb/pip_package/build_pip_package %s" % whl_build_opts

        run_shell_cmd(whl_cmd)

        # install wheel with pip
        pymajmin = ''.join(get_software_version('Python').split('.')[:2])
        whl_file = '%s-%s-cp%s*.whl' % (self.name.replace('-', '_'), self.version, pymajmin)
        whl_path = os.path.join(self.builddir, whl_file)

        installopts = ' '.join([self.cfg['installopts']] + self.py_installopts)

        self.install_cmd = PIP_INSTALL_CMD % {
            'installopts': installopts,
            'loc': whl_path,
            'prefix': self.installdir,
            'python': self.python_cmd,
        }

        return super(EB_dm_minus_reverb, self).install_step(*args, **kwargs)
