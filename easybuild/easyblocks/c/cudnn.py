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
EasyBuild support for cuDNN, implemented as an easyblock

@author: Simon Branford (University of Birmingham)
"""
from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.systemtools import POWER, X86_64, get_cpu_architecture


class EB_cuDNN(Tarball):
    """Support for building cuDNN."""

    def __init__(self, *args, **kwargs):
        """ Init the cuDNN easyblock adding a new cudnnarch template var """
        myarch = get_cpu_architecture()
        if myarch == X86_64:
            cudnnarch = 'x64'
        elif myarch == POWER:
            cudnnarch = 'ppc64le'
        else:
            raise EasyBuildError("Architecture %s is not supported for cuDNN on EasyBuild", myarch)

        super(EB_cuDNN, self).__init__(*args, **kwargs)

        self.cfg.template_values['cudnnarch'] = cudnnarch
        self.cfg.generate_template_values()
