##
# This file is an EasyBuild reciPY as per https://github.com/hpcugent/easybuild
#
# Copyright:: Copyright 2012-2013 University of Luxembourg/Luxembourg Centre for Systems Biomedicine
# Authors::   Robert Schmidt <roschmidt@ohri.ca>,Cedric Laczny <cedric.laczny@uni.lu>, Fotis Georgatos <fotis.georgatos@uni.lu>, Kenneth Hoste
# License::   MIT/GPL
# $Id$
#
##
"""
EasyBuild support for building BCFtools (BCF - Binary VCF - Variant Call Format), implemented as an easyblock

@author: Robert Schmidt (Ottawa Hospital Research Institute)
@author: Cedric Laczny (Uni.Lu)
@author: Fotis Georgatos (Uni.Lu)
@author: Kenneth Hoste (Ghent University)
"""
import os
import shutil
import stat
from distutils.version import LooseVersion

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.filetools import adjust_permissions

class EB_BCFtools(ConfigureMake):
    """
    Support for building BCFtools; 
    Specs for the formats can be found here:
    https://github.com/samtools/hts-specs
    """

    def __init__(self, *args, **kwargs):
        """Define lists of files to install."""
        super(EB_BCFtools, self).__init__(*args, **kwargs)

        self.bin_files = ["vcfutils.pl", "bcftools",
                          "plot-vcfstats"]

    def configure_step(self):
        """
        No configure
        """
        pass

    def install_step(self):
        """
        Install by copying files to install dir
        """

        for (srcdir, dest, files) in [
                                      (self.cfg['start_dir'], 'bin', self.bin_files),
                                     ]:

            destdir = os.path.join(self.installdir, dest)
            srcfile = None
            try:
                os.makedirs(destdir)
                for filename in files:
                    srcfile = os.path.join(srcdir, filename)
                    shutil.copy2(srcfile, destdir)
            except OSError, err:
                self.log.error("Copying %s to installation dir %s failed: %s" % (srcfile, destdir, err))

        # fix permissions so ownwer group and others have R-X
        adjust_permissions(self.installdir, stat.S_IRGRP|stat.S_IXGRP|stat.S_IROTH|stat.S_IXOTH, add=True, recursive=True)

    def sanity_check_step(self):
        """Custom sanity check for BCFtools."""

        custom_paths = {
                        'files': ['bin/%s' % x for x in [f.split('/')[-1] for f in self.bin_files]] ,
                        'dirs': []
                       }

        super(EB_BCFtools, self).sanity_check_step(custom_paths=custom_paths)
