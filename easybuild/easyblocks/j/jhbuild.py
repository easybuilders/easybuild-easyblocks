##
# Copyright 2016 Forschungszentrum Juelich GmbH
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
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
@author: Damian Alvarez (Forschungszentrum Juelich GmbH)
"""

import shutil
import os
import stat

from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import source_paths
from easybuild.tools.run import run_cmd


class EB_jhbuild(EasyBlock):
    """
    Support for building and installing applications with jhbuild
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to EB_jhbuild."""
        extra_vars = EasyBlock.extra_options(extra=extra_vars)
        extra_vars.update({
            'jhbuildrc_file': ['jhbuildrc', "File that contains the jhbuild configuration", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Skip the install step."""
        super(EB_jhbuild, self).__init__(*args, **kwargs)
        self.cfg['skipsteps'] = "install"

    def extract_step(self):
        """Move all source files to the build directory"""

        #self.src[0]['finalpath'] = self.builddir

        # This code is copy and paste from the extract method in binary.py
        # copy source to build dir.
        for source in self.src:
            src = source['path']
            dst = os.path.join(self.builddir, source['name'])
            try:
                shutil.copy2(src, self.builddir)
                os.chmod(dst, stat.S_IRWXU)
            except (OSError, IOError), err:
                raise EasyBuildError("Couldn't copy %s to %s: %s", src, self.builddir, err)

    def configure_step(self, cmd_prefix='', verbose=False, path=None):
        """
        Configure step
        - Make sure it is using the python installed by EB, set convenient variables to be used
          by the configuration file, and set the proper download path. Also run a "sanity check"
          to verify that the environment is in good shape
        """

        # [Re]define the download directory and make sure that our python is used
        self.log.info('Loading Python to get the correct paths to be used in %s' % self.cfg['jhbuildrc_file'])
        download_path = os.path.join(source_paths()[0], self.name[0].lower(), self.name)
        tarballdir = 'tarballdir = "%s"' % download_path
        pythonpath = os.getenv('PYTHONPATH', None)
        python_root = os.getenv('EBROOTPYTHON', None)
        if python_root == None:
            raise EasyBuildError("Python is not loaded")

        try:
            self.log.info('Appending PYTHONPATH and PYTHON definitions to %s' % self.cfg['jhbuildrc_file'])
            self.log.info('Appending "%s" to %s' % (tarballdir, self.cfg['jhbuildrc_file']))
            with open(self.cfg['jhbuildrc_file'], "a") as conf_file:
                if pythonpath != None:
                    conf_file.write("addpath('PYTHONPATH', '%s')\n" % pythonpath)
                conf_file.write("os.environ['PYTHON'] = '%s/bin/python'\n" % python_root)
                conf_file.write(tarballdir + "\n")
        except OSError, err:
            raise EasyBuildError("Can't append to %s: %s", self.cfg['jhbuildrc_file'], err)

        # This enables external scripts (like jhbuildrc) to reference EB paths
        self.log.info("Setting EBBUILDDIR=%s to be used by %s if necessary" % (self.builddir, self.cfg['jhbuildrc_file']))
        os.environ['EBBUILDDIR'] = self.builddir
        self.log.info("Setting EBINSTALLDIR=%s to be used by %s if necessary" % (self.installdir, self.cfg['jhbuildrc_file']))
        os.environ['EBINSTALLDIR'] = self.installdir
        
        # Check the environment
        cmd = "%s jhbuild sanitycheck" % self.cfg['prebuildopts']

        (out, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)

        return out

    def build_step(self, verbose=False, path=None):
        """
        Start the actual build
        - typical: jhbuild --no-interact -f jhbuildrc
        """

        paracmd = '--no-interact -f %s' % self.cfg['jhbuildrc_file']

        cmd = "%s jhbuild %s %s" % (self.cfg['prebuildopts'], paracmd, self.cfg['buildopts'])

        (out, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)

        return out
