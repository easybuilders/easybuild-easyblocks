##
# Copyright 2009-2013 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
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
EasyBuild support for SPM, implemented as an easyblock

@authors: Stijn De Weirdt (UGent), Dries Verdegem (UGent), Kenneth Hoste (UGent), Pieter De Baets (UGent),
          Jens Timmerman (UGent)
"""
import os
import shutil
import distutils.core

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.filetools import run_cmd


class EB_SPM(EasyBlock):
    """Support for building and installing SPM."""

    def __init__(self,*args,**kwargs):
        """Specify building in install dir, initialize custom variables."""

        super(EB_SPM, self).__init__(*args, **kwargs)
        
	self.build_in_installdir = True

    def extract_step(self):
	super(EB_SPM, self).extract_step()
	
	# there is no --strip-components for unzip...
	for files in os.listdir(self.src[0]['finalpath']):
	    shutil.move(files, self.builddir)
	# shutil.rmtree(self.src[0]['finalpath']) - why does this break stuff in the prepare step?
	self.cfg['start_dir'] = os.path.join(self.builddir, "src/")

    def configure_step(self):
        """No configure step for SPM."""
        pass

    def build_step(self):
        """Custom build procedure for SPM"""
	
	# MATLAB (mcc) warns if GCC version is not 4.4.x, but it still seems to work
	
	# is there a better way to express a dependency on the loaded MATLAB module?
	matlab_root = get_software_root('MATLAB')
	if not matlab_root:
	    self.log.error("MATLAB module not loaded")
		
	cmd = "make install"
	(out, _) = run_cmd(cmd, log_all=True, simple=False)

	return out

    def install_step(self):
	pass

    def sanity_check_step(self):
        """Custom sanity check for SPM."""

        custom_paths = {
                        'files': [ 'spm.m' ],
                        'dirs':[]
                        }

        super(EB_SPM, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Custom extra module file entries for SPM."""
        txt = super(EB_SPM, self).make_module_extra()

        txt += self.moduleGenerator.prepend_paths("MATLABPATH", "")

        return txt
	
