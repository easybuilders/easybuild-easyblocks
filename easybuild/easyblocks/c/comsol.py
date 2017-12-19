##
# This file is an EasyBuild reciPY as per https://github.com/easybuilders/easybuild
##
"""
EasyBuild support for installing COMSOL, implemented as an easyblock

@author: Mikael OEhman (Chalmers University of Technology)
"""

import re
import shutil
import os
import stat

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import read_file, write_file
from easybuild.tools.run import run_cmd


class EB_COMSOL(PackedBinary):
    """Support for installing COMSOL."""

    def __init__(self, *args, **kwargs):
        super(EB_COMSOL, self).__init__(*args, **kwargs)
        self.configfile = os.path.join(self.builddir, 'my_setupconfig.ini')

    def configure_step(self):
        license = os.getenv('EB_COMSOL_LICENSE')
        if license is None:
            raise EasyBuildError("EB_COMSOL_LICENSE not set (required)")

        try:
            shutil.copyfile(os.path.join(self.cfg['start_dir'], 'setupconfig.ini'), self.configfile)
            config = read_file(self.configfile)

            reginst = re.compile("^installdir =.*", re.M)
            reggui = re.compile("^showgui =.*", re.M)
            regagree = re.compile("^agree =.*", re.M)
            reglic = re.compile("^license =.*", re.M)
            reglicman = re.compile("^licmanager =.*", re.M)
            regmenu = re.compile("^startmenushortcuts =.*", re.M)
            regdesk = re.compile("^desktopshortcuts =.*", re.M)
            reglaunch = re.compile("^linuxlauncher =.*", re.M)
            regsym = re.compile("^symlinks =.*", re.M)
            regfire = re.compile("^firewall =.*", re.M)

            config = reginst.sub("installdir=%s" % self.installdir, config)
            config = reggui.sub("showgui = 0", config)
            config = regagree.sub("agree = 1", config)
            config = reglic.sub("license = %s" % license, config)
            config = reglicman.sub("licmanager = 0", config)
            config = regmenu.sub("startmenushortcuts = 0", config)
            config = regdesk.sub("desktopshortcuts = 0", config)
            config = reglaunch.sub("linuxlauncher = 0", config)
            config = regsym.sub("symlinks = 0", config)
            config = regfire.sub("firewall = 0", config)

            write_file(self.configfile, config)

        except IOError, err:
            raise EasyBuildError("Failed to create installation config file %s: %s", self.configfile, err)

    def install_step(self):
        run_cmd("./setup -s %s" % self.configfile, log_all=True, simple=True)

    def make_module_extra(self):
        txt = super(EB_COMSOL, self).make_module_extra()
        txt += self.module_generator.prepend_paths("PATH", ['bin'])
        return txt

    def sanity_check_step(self):
        custom_paths = {
            'files': ['bin/comsol'],
            'dirs': [],
        }
        super(EB_COMSOL, self).sanity_check_step(custom_paths=custom_paths)
