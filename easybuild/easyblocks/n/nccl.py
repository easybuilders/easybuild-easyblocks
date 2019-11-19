##
# This file is an EasyBuild reciPY as per https://github.com/easybuilders/easybuild
#
# Copyright:: Copyright 2012-2019 Uni.Lu/LCSB, NTUA
# Authors::   Simon Branford
# License::   MIT/GPL
# $Id$
#
# This work implements a part of the HPCBIOS project and is a component of the policy:
# http://hpcbios.readthedocs.org/en/latest/
##
"""
EasyBuild support for NCCL, implemented as an easyblock

@author: Simon Branford (University of Birmingham)
"""
import os
import shutil

from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.tools.systemtools import POWER, X86_64, get_cpu_architecture


class EB_NCCL(MakeCp):
    """Support for building NCCL."""

    def __init__(self, *args, **kwargs):
        """ Init the NCCL easyblock adding a new ncclarch template var """
        myarch = get_cpu_architecture()
        if myarch == X86_64:
            ncclarch = 'x86_64'
        elif myarch == POWER:
            ncclarch = 'ppc64le'
        else:
            raise EasyBuildError("Architecture %s is not supported for NCCL on EasyBuild", myarch)

        super(EB_NCCL, self).__init__(*args, **kwargs)

        self.cfg.template_values['ncclarch'] = ncclarch
        self.cfg.generate_template_values()
