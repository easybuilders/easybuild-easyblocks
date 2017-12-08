##
# Copyright 2009-2017 Ghent University
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
EasyBuild support for installing Comsol, implemented as an easyblock

@author: Ake Sandgren (HPC2N, Umea University)
"""
import re
import os
import shutil
import stat

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, find_flexlm_license, read_file, write_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_Comsol(PackedBinary):
    """Support for installing COMSOL."""

    def __init__(self, *args, **kwargs):
        """Add extra config options specific to COMSOL."""
        super(EB_Comsol, self).__init__(*args, **kwargs)
        self.comp_fam = None
        self.configfile = os.path.join(self.builddir, 'my_setupconfig.ini')

    def configure_step(self):
        """Configure COMSOL installation: create license file."""

        # The tar file comes from the DVD and has 0444 as permission at
        # the top dir.
        adjust_permissions(self.cfg['start_dir'], stat.S_IWUSR)

        default_lic_env_var = 'LM_LICENSE_FILE'
        lic_specs, self.license_env_var = find_flexlm_license(custom_env_vars=[default_lic_env_var],
            lic_specs=[self.cfg['license_file']])

        if lic_specs:
            if self.license_env_var is None:
                self.log.info("Using Comsol license specifications from 'license_file': %s", lic_specs)
                self.license_env_var = default_lic_env_var
            else:
                self.log.info("Using Comsol license specifications from $%s: %s", self.license_env_var, lic_specs)

            self.license_file = os.pathsep.join(lic_specs)
            env.setvar(self.license_env_var, self.license_file)
        else:
            msg = "No viable license specifications found; "
            msg += "specify 'license_file', or define $LM_LICENSE_FILE"
            raise EasyBuildError(msg)

        try:
            shutil.copyfile(os.path.join(self.cfg['start_dir'], 'setupconfig.ini'), self.configfile)
            config = read_file(self.configfile)

            regdest = re.compile(r"^installdir\s*=.*", re.M)
            reggui = re.compile(r"^showgui\s*=.*", re.M)
            regagree = re.compile(r"^agree\s*=.*", re.M)
            reglicpath = re.compile(r"^license\s*=.*", re.M)
            reglinuxlauncher = re.compile(r"^linuxlauncher\s*=.*", re.M)
            regsymlinks = re.compile(r"^symlinks\s*=.*", re.M)
            regfileassoc = re.compile(r"^fileassoc\s*=.*", re.M)

            config = regdest.sub("installdir=%s" % self.installdir, config)
            config = reggui.sub("showgui=0", config)
            config = regagree.sub("agree=1", config)
            config = reglicpath.sub("license=%s" % self.license_file, config)
            config = reglinuxlauncher.sub("linuxlauncher=0", config)
            config = regsymlinks.sub("symlinks=0", config)
            config = regfileassoc.sub("fileassoc=0", config)

            matlab_root = get_software_root("MATLAB")
            if matlab_root:
                regmatlab = re.compile(r"^matlabdir\s*=.*", re.M)
                config = regmatlab.sub("matlabdir=%s" % matlabroot, config)

            write_file(self.configfile, config)

        except IOError, err:
            raise EasyBuildError("Failed to create installation config file %s: %s", self.configfile, err)

        self.log.debug('configuration file written to %s:\n %s', self.configfile, config)

    def install_step(self):
        """COMSOL install procedure using 'install' command."""

        src = os.path.join(self.cfg['start_dir'], 'setup')

        # make sure setup script is executable
        adjust_permissions(src, stat.S_IXUSR)

        # make sure $DISPLAY is not defined, which may lead to (hard to trace) problems
        # this is a workaround for not being able to specify --nodisplay to the install scripts
        if 'DISPLAY' in os.environ:
            os.environ.pop('DISPLAY')

        cmd = "%s ./setup -s %s %s" % (self.cfg['preinstallopts'], self.configfile, self.cfg['installopts'])
        run_cmd(cmd, log_all=True, simple=True)

    def sanity_check_step(self):
        """Custom sanity check for COMSOL."""
        custom_paths = {
            'files': [
                "bin/comsol", "bin/glnxa64/comsol",
                "lib/glnxa64/libcscomsolgeom.%s" % get_shared_lib_ext(),
            ],
            'dirs': ["java/glnxa64", "plugins"],
        }
        super(EB_Comsol, self).sanity_check_step(custom_paths=custom_paths)
