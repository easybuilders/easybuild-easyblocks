##
#
# CeCILL-B FREE SOFTWARE LICENSE AGREEMENT
#
# This Agreement is a Free Software license agreement that is the result
# of discussions between its authors in order to ensure compliance with
# the two main principles guiding its drafting:
#
#     * firstly, compliance with the principles governing the distribution
#       of Free Software: access to source code, broad rights granted to
#       users,
#     * secondly, the election of a governing law, French law, with which
#       it is conformant, both as regards the law of torts and
#       intellectual property law, and the protection that it offers to
#    both authors and holders of the economic rights over software.
#
# Copyright:: Copyright 2014 - EDF
# Authors::   EDF CCN HPC <dsp-cspito-ccn-hpc@edf.fr>
# License::   CeCILL-B (see http://cecill.info/licences.en.html for more information)
#
##
"""
EasyBuild support for building and installing XERCES library, implemented as an easyblock

@author: CCN HPC (EDF)
@author: Kenneth Hoste  (Ghent University)
"""

import os
import shutil
import platform
import easybuild.tools.environment as env

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.environment import setvar
from easybuild.tools.filetools import run_cmd

class EB_XERCES(ConfigureMake):
    """
    Support for building XERCES Library
    - go to $XERCESCROOT/src/xercesc directory 
    - configure with runConfigure -options
    - build with make and install
    """

    def configure_step(self, subdir=None):

        """
        Go to the build directory
        Run the runConfigure wrapper script
        """
        env.setvar('XERCESCROOT', self.cfg['start_dir'])

        setupdir = os.path.join(self.cfg['start_dir'], 'src', 'xercesc')
        try:
            os.chdir(setupdir)
        except OSError, err:
            self.log.error("Failed to change to to dir % s: % s" % (setupdir, err))

        self.cfg.update('configopts', '-p % s -c"$CC" -x"$CXX" -minmem -nsocket -tnative -rpthread' % platform.system().lower())

        cmd = "./runConfigure % s -P % s" % (self.cfg['configopts'], self.installdir)
        run_cmd(cmd, log_all=True, simple=True, log_output=True)


    def build_step(self):

        """
        Build with make 
        """
        self.cfg['parallel'] = 1
        super(EB_XERCES, self).build_step()


    def sanity_check_step(self):

        """
        Custom sanity check for Xerces
        """

        custom_paths = {
                        'files': ["lib/libxerces-c.so.28"],
                        'dirs': ['include']
                       }

        super(EB_XERCES, self).sanity_check_step(custom_paths)
