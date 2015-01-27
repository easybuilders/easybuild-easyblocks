##
# This file is an EasyBuild reciPY as per https://github.com/hpcugent/easybuild
#
# Copyright:: Copyright 2012-2014 Uni.Lu/LCSB, NTUA
# Authors::   Cedric Laczny <cedric.laczny@uni.lu>, Fotis Georgatos <fotis@cern.ch>, Kenneth Hoste
# License::   MIT/GPL
# $Id$
#
# This work implements a part of the HPCBIOS project and is a component of the policy:
# http://hpcbios.readthedocs.org/en/latest/HPCBIOS_2012-90.html
##
"""
Easybuild support for building ncurses, implemented as an easyblock

@author: Cedric Laczny (Uni.Lu)
@author: Fotis Georgatos (Uni.Lu)
@author: Kenneth Hoste (Ghent University)
@author: Ward Poelmans (Ghent University)
"""

from easybuild.easyblocks.generic.configuremake import ConfigureMake


class EB_ncurses(ConfigureMake):
    """
    Old easyblock for ncurses, superseded by easyconfigs
    """
    def __init__(self, *args, **kwargs):
        super(EB_ncurses, self).__init__(*args, **kwargs)
        url = "https://github.com/hpcugent/easybuild-easyconfigs/tree/develop/easybuild/easyconfigs/n/ncurses"
        self.log.error("EB_ncurses: easyblock has been removed in favor of new easyconfigs: %s" % url)
