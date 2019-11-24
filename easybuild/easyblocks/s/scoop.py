##
# Copyright 2009-2019 Ghent University
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
EasyBuild support for SCOOP, implemented as an easyblock

@author: Samuel Moors, Vrije Universiteit Brussel (VUB)
"""
import os
import re

from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.framework.easyconfig.easyconfig import ActiveMNS
from easybuild.tools.filetools import apply_regex_substitutions
from easybuild.tools.modules import get_software_version


class EB_SCOOP(PythonPackage):
    """Support for building SCOOP"""

    def install_step(self):
        """
        Patch for launching the broker and workers over ssh
        Emulate login shell and load SCOOP module
        """

        super(EB_SCOOP, self).install_step()

        login_shell = 'source /etc/profile && '
        login_shell += '(source ~/.bash_profile || source ~/.bash_login || source ~/.profile || echo)'
        mod_name = ActiveMNS().det_full_module_name(self.cfg)
        set_env = "'%s && module load %s && '" % (login_shell, mod_name)
        pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
        base_path = os.path.join(self.installdir, 'lib', 'python%s' % pyshortver, 'site-packages', 'scoop', 'launch')

        # patch workerLaunch.py
        sub = """subprocess.Popen(sshCmd + [
                    self.hostname,
                    %s,
                    self.getCommand(),
                ],""" % set_env
        regex = re.escape('subprocess.Popen(sshCmd + [self.hostname, self.getCommand()],')
        apply_regex_substitutions(os.path.join(base_path, 'workerLaunch.py'), [(regex, sub)])

        # patch brokerLaunch.py
        sub = """%s,
                brokerString.format(brokerPort=i,""" % set_env
        regex = re.escape('brokerString.format(brokerPort=i,')
        apply_regex_substitutions(os.path.join(base_path, 'brokerLaunch.py'), [(regex, sub)])
