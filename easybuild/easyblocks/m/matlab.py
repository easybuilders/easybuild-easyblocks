##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for installing MATLAB, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Fotis Georgatos (Uni.Lu, NTUA)
"""
import re
import os
import stat
import tempfile

from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, change_dir, copy_file, read_file, write_file
from easybuild.tools.py2vs3 import string_type
from easybuild.tools.run import run_cmd


class EB_MATLAB(PackedBinary):
    """Support for installing MATLAB."""

    def __init__(self, *args, **kwargs):
        """Add extra config options specific to MATLAB."""
        super(EB_MATLAB, self).__init__(*args, **kwargs)
        self.comp_fam = None
        self.configfile = os.path.join(self.builddir, 'my_installer_input.txt')
        self.outputfile = os.path.join(self.builddir, 'my_installer_output.txt')

    @staticmethod
    def extra_options():
        extra_vars = {
            'java_options': ['-Xmx256m', "$_JAVA_OPTIONS value set for install and in module file.", CUSTOM],
            'key': [None, "Installation key(s), make one install for each key. Single key or a list of keys", CUSTOM],
        }
        return PackedBinary.extra_options(extra_vars)

    def configure_step(self):
        """Configure MATLAB installation: create license file."""

        licfile = self.cfg['license_file']
        if licfile is None:
            licserv = self.cfg['license_server']
            if licserv is None:
                licserv = os.getenv('EB_MATLAB_LICENSE_SERVER', 'license.example.com')
            licport = self.cfg['license_server_port']
            if licport is None:
                licport = os.getenv('EB_MATLAB_LICENSE_SERVER_PORT', '00000')
            # create license file
            lictxt = '\n'.join([
                "SERVER %s 000000000000 %s" % (licserv, licport),
                "USE_SERVER",
            ])

            licfile = os.path.join(self.builddir, 'matlab.lic')
            write_file(licfile, lictxt)

        try:
            copy_file(os.path.join(self.cfg['start_dir'], 'installer_input.txt'), self.configfile)
            adjust_permissions(self.configfile, stat.S_IWUSR)

            # read file in binary mode to avoid UTF-8 encoding issues when using Python 3,
            # due to non-UTF-8 characters...
            config = read_file(self.configfile, mode='rb')

            # use raw byte strings (must be 'br', not 'rb'),
            # required when using Python 3 because file was read in binary mode
            regdest = re.compile(br"^# destinationFolder=.*", re.M)
            regagree = re.compile(br"^# agreeToLicense=.*", re.M)
            regmode = re.compile(br"^# mode=.*", re.M)
            reglicpath = re.compile(br"^# licensePath=.*", re.M)
            regoutfile = re.compile(br"^# outputFile=.*", re.M)

            # must use byte-strings here when using Python 3, see above
            config = regdest.sub(b"destinationFolder=%s" % self.installdir.encode('utf-8'), config)
            config = regagree.sub(b"agreeToLicense=Yes", config)
            config = regmode.sub(b"mode=silent", config)
            config = reglicpath.sub(b"licensePath=%s" % licfile.encode('utf-8'), config)
            config = regoutfile.sub(b"outputFile=%s" % self.outputfile.encode('utf-8'), config)

            write_file(self.configfile, config)

        except IOError as err:
            raise EasyBuildError("Failed to create installation config file %s: %s", self.configfile, err)

        self.log.debug('configuration file written to %s:\n %s', self.configfile, config)

    def install_step(self):
        """MATLAB install procedure using 'install' command."""

        src = os.path.join(self.cfg['start_dir'], 'install')

        # make sure install script is executable
        adjust_permissions(src, stat.S_IXUSR)

        if LooseVersion(self.version) >= LooseVersion('2016b'):
            perm_dirs = [os.path.join(self.cfg['start_dir'], 'bin', 'glnxa64')]
            if LooseVersion(self.version) < LooseVersion('2021b'):
                jdir = os.path.join(self.cfg['start_dir'], 'sys', 'java', 'jre', 'glnxa64', 'jre', 'bin')
                perm_dirs.append(jdir)
            for perm_dir in perm_dirs:
                adjust_permissions(perm_dir, stat.S_IXUSR)

        # make sure $DISPLAY is not defined, which may lead to (hard to trace) problems
        # this is a workaround for not being able to specify --nodisplay to the install scripts
        if 'DISPLAY' in os.environ:
            os.environ.pop('DISPLAY')

        if '_JAVA_OPTIONS' not in self.cfg['preinstallopts']:
            java_opts = 'export _JAVA_OPTIONS="%s" && ' % self.cfg['java_options']
            self.cfg['preinstallopts'] = java_opts + self.cfg['preinstallopts']
        if LooseVersion(self.version) >= LooseVersion('2016b'):
            change_dir(self.builddir)

        # Build the cmd string
        cmdlist = [
            self.cfg['preinstallopts'],
            src,
            '-inputFile',
            self.configfile,
        ]
        if LooseVersion(self.version) < LooseVersion('2020a'):
            # MATLAB installers < 2020a ignore $TMPDIR (always use /tmp) and might need a large tmpdir
            tmpdir = tempfile.mkdtemp()
            cmdlist.extend([
                '-v',
                '-tmpdir',
                tmpdir,
            ])
        cmdlist.append(self.cfg['installopts'])
        cmd = ' '.join(cmdlist)

        keys = self.cfg['key']
        if keys is None:
            try:
                keys = os.environ['EB_MATLAB_KEY']
            except KeyError:
                raise EasyBuildError("The MATLAB install key is not set. This can be set either with the environment "
                                     "variable EB_MATLAB_KEY or by the easyconfig variable 'key'.")
        if isinstance(keys, string_type):
            keys = keys.split(',')

        # Compile the installation key regex outside of the loop
        regkey = re.compile(br"^(# )?fileInstallationKey=.*", re.M)

        # Run an install for each key
        for i, key in enumerate(keys):

            self.log.info('Installing MATLAB with key %s of %s', i + 1, len(keys))

            try:
                config = read_file(self.configfile, mode='rb')
                config = regkey.sub(b"fileInstallationKey=%s" % key.encode('utf-8'), config)
                write_file(self.configfile, config)

            except IOError as err:
                raise EasyBuildError("Failed to update config file %s: %s", self.configfile, err)

            (out, _) = run_cmd(cmd, log_all=True, simple=False)

            # check installer output for known signs of trouble
            patterns = [
                "Error: You have entered an invalid File Installation Key",
                "Not a valid key",
                "All selected products are already installed",
                "The application encountered an unexpected error and needs to close",
                "Error: Unable to write to",
                "Exiting with status -\\d",
                "End - Unsuccessful",
            ]

            for pattern in patterns:
                regex = re.compile(pattern, re.I)
                if regex.search(out):
                    raise EasyBuildError("Found error pattern '%s' in output of installation command '%s': %s",
                                         regex.pattern, cmd, out)
                with open(self.outputfile) as f:
                    if regex.search(f.read()):
                        raise EasyBuildError("Found error pattern '%s' in output file of installer",
                                             regex.pattern)

    def sanity_check_step(self):
        """Custom sanity check for MATLAB."""
        custom_paths = {
            'files': ["bin/matlab", "bin/glnxa64/MATLAB", "toolbox/local/classpath.txt"],
            'dirs': ["java/jar"],
        }
        super(EB_MATLAB, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Extend PATH and set proper _JAVA_OPTIONS (e.g., -Xmx)."""
        txt = super(EB_MATLAB, self).make_module_extra()

        if self.cfg['java_options']:
            txt += self.module_generator.set_environment('_JAVA_OPTIONS', self.cfg['java_options'])
        return txt
