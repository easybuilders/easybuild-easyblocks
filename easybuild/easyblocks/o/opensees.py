##
# Copyright 2013 Ghent University
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
EasyBuild support for building and installing OpenSees, implemented as an easyblock

@author: Bart Verleye (the University of Auckland)
"""
import os

from easybuild.tools.filetools import run_cmd
from easybuild.tools.modules import get_software_root
from easybuild.easyblocks.generic.makecp import MakeCp


class EB_OpenSees(MakeCp):
    """Support for building and installing OpenSees."""

    def configure_step(self):
         f=open('Makefile.def','w');
         txt='\n'.join([
         "PROGRAMMING_MODE=PARALLEL_INTERPRETERS",
		 "PROGRAMMING_FLAG = -D_PARALLEL_INTERPRETERS",
         "BASE=''",
         "HOME=%s/OpenSees" %self.builddir,  
         "FE=$(HOME)/SRC",
         "OpenSees_PROGRAM=$(HOME)/bin/OpenSeesMP",
         "OPERATING_SYSTEM=LINUX",
         "GRAPHICS=NONE",
         "GRAPHIC_FLAG=-D_NOGRAPHICS",
         "DEBUG_MODE=NO_DEBUG", 
         "RELIABILITY=NO_RELIABILITY",
         "AMDdir=$EBROOTAMD",
         "CBLASdir=$CBLAS_LIB_DIR", 
         "SUPERLUdir=$EBROOTSUPERLU",
         "AMDdir=$(HOME)/OTHER/AMD",
         "CBLASdir=$(HOME)/OTHER/CBLAS",
         "SUPERLU_DISTdir=$(HOME)/OTHER/SuperLU_DIST_2.5/SRC",
         "SUPERLUdir=$(HOME)/OTHER/SuperLU_4.1/SRC",
         "ARPACKdir=$(HOME)/OTHER/ARPACK",
         "UMFPACKdir=$(HOME)/OTHER/UMFPACK",
         "CSPARSEdir=$(HOME)/OTHER/CSPARSE",
         "SRCdir=$(HOME)/SRC",
         "DIRS = $(CBLASdir) $(AMDdir) $(CSPARSEdir) $(SUPERLUdir) $(SUPERLU_DISTdir) $(ARPACKdir) $(UMFPACKdir) $(SRCdir)",
         "WIPE_LIBS   = $(FE_LIBRARY) $(CBLAS_LIBRARY) $(ARPACK_LIBRARY) $(UMFPACK_LIBRARY) $(CSPARSE_LIBRARY) $(DISTRIBUTED_SUPERLU_LIBRARY) $(METIS_LIBRARY)",
         "FE_LIBRARY      = $(HOME)/lib/libOpenSees.a",
         "SUPERLU_LIBRARY = $(HOME)/lib/libSuperLU.a",
         "CBLAS_LIBRARY   = $(HOME)/lib/libCBlas.a",
         "ARPACK_LIBRARY  = $(HOME)/lib/libArpack.a",
         "AMD_LIBRARY  = $(HOME)/lib/libAMD.a",
         "UMFPACK_LIBRARY = $(HOME)/lib/libUmfpack.a",
         "CSPARSE_LIBRARY   = $(HOME)/lib/libCSparse.a",
         "DISTRIBUTED_SUPERLU_LIBRARY     = $(HOME)/lib/libDistributedSuperLU.a",
         "SCALAPACK_LIBRARY  = -L%s %s" % (os.getenv('SCALAPACK_LIB_DIR'), os.getenv('LIBSCALAPACK')),
         "LAPACK_LIBRARY  = -L%s %s" % (os.getenv('LAPACK_LIB_DIR'), os.getenv('LIBLAPACK')),
         "BLAS_LIBRARY    = -L%s %s" % (os.getenv('BLAS_LIB_DIR'), os.getenv('LIBBLAS')),
         "METIS_LIBRARY = -L%s -lparmetis -lmetis" % os.path.join(get_software_root('ParMETIS'), 'lib'),
         "BLACS_LIBRARY = -L%s -lblacs -lblacsCinit" % os.path.join(get_software_root('BLACS'), 'lib'),
         "SCOTCH_LIBRARY = -L%s -lesmumps  -lptesmumps  -lptscotch  -lptscotcherr  -lptscotcherrexit -lscotch  -lscotcherr  -lscotcherrexit  -lscotch_group" %os.path.join(get_software_root('SCOTCH'), 'lib'),
         "MACHINE_NUMERICAL_LIBS  = -lm $(ARPACK_LIBRARY) $(SUPERLU_LIBRARY) $(UMFPACK_LIBRARY) $(CSPARSE_LIBRARY) $(LAPACK_LIBRARY) $(BLAS_LIBRARY) $(CBLAS_LIBRARY) $(AMD_LIBRARY) $(GRAPHIC_LIBRARY) ",
		 "CC++ = $(MPICXX)",
         "CC = $(MPICC)",
         "FC = $(MPIF90)",
         "C++FLAGS=-Wall  -D_LINUX -D_UNIX  -D_TCL85 $(GRAPHIC_FLAG) $(RELIABILITY_FLAG) $(DEBUG_FLAG) $(PROGRAMMING_FLAG) $(MUMPS_FLAG) -O3 -ffloat-store",
         "CFLAGS=-Wall -O2",
         "FFLAGS=-Wall -O -lstdc++",
         "LINKER=$(CC++)",
         "LINKFLAGS=-rdynamic -Wall",
         "MAKE=make",
         "CD=cd",
         "ECHO=echo",
         "RM=rm",
         "RMFLAGS=-f",
         "SHELL=/bin/sh",
         ".SUFFIXES:  .C .c .f .f90 .cpp .o .cpp",
         ".DEFAULT:",
         "\t@$(ECHO) \"Unknown target $@, try:  make help\"",
         ".cpp.o:",
         "\t@$(ECHO) Making $@ from $<",
         "\t$(CC++) $(C++FLAGS) $(INCLUDES) -c $< -o $@",
         ".C.o:",
         "\t@$(ECHO) Making $@ from $<",
         "\t$(CC++) $(C++FLAGS) $(INCLUDES) -c $< -o $@",
         ".c.o:",
         "\t@$(ECHO) Making $@ from $<",
         "\t$(CC) $(CFLAGS) -c $< -o $@",
         ".f.o:",
         "\t@$(ECHO) Making $@ from $<",
         "\t$(FC) $(FFLAGS) -c $< -o $@",
         "HAVEMUMPS=YES",
         "MUMPS_DIR = %s" % get_software_root('MUMPS'),
         "MUMPS = YES",
         "MUMPS_FLAG = -D_MUMPS",
         "MUMPS_LIB = $(FE)/system_of_eqn/linearSOE/mumps/MumpsSOE.o $(FE)/system_of_eqn/linearSOE/mumps/MumpsSolver.o $(FE)/system_of_eqn/linearSOE/mumps/MumpsParallelSOE.o $(FE)/system_of_eqn/linearSOE/mumps/MumpsParallelSolver.o -L$(MUMPS_DIR)/lib -ldmumps   -lmumps_common -lpord -lcmumps $(SCALAPACK_LIBRARY) $(BLACS_LIBRARY) $(BLAS_LIBRARY) $(LAPACK_LIBRARY) $(METIS_LIBRARY) $(SCOTCH_LIBRARY)",
         "MUMPS_INCLUDE = -I$(MUMPS_DIR)/include",
         "MACHINE_INCLUDES  = -I$(BASE)/include -I$(SUPERLU_DISTdir) $(MUMPS_INCLUDE)",
         "MACHINE_SPECIFIC_LIBS = $(MUMPS_LIB)",
         "PARALLEL_LIB = $(FE)/system_of_eqn/linearSOE/sparseGEN/DistributedSparseGenColLinSOE.o $(FE)/system_of_eqn/linearSOE/sparseGEN/DistributedSuperLU.o $(DISTRIBUTED_SUPERLU_LIBRARY) ",
		 "include $(FE)/Makefile.incl",
         "INCLUDES =  $(TCL_INCLUDES) $(FE_INCLUDES) $(MACHINE_INCLUDES)",
         "TCL_LIBRARY = %s/libtcl8.5.so" % os.path.join(get_software_root('Tcl'), 'lib'),
         "TCL_INCLUDES = -I%s" % os.path.join(get_software_root('Tcl'), 'include'),
         ])
         f.write(txt)
         f.close()
        
    def build_step(self):
        "Build OpenSees using make after sourcing script to set environment."
        if not os.path.exists(os.path.join(self.builddir, 'OpenSees/bin')):
            os.makedirs(os.path.join(self.builddir, 'OpenSees/bin'))
        if not os.path.exists(os.path.join(self.builddir, 'OpenSees/lib')):
            os.makedirs(os.path.join(self.builddir, 'OpenSees/lib'))

        # make directly in install directory
        cmd="make"
        run_cmd(cmd,log_all=True,simple=True,log_output=True)

        text = open("Makefile.def").read()
        text = '\n'.join("PROGRAMMING_MODE=PARALLEL" if line.startswith("PROGRAMMING_MODE") else line
                              for line in text.splitlines())
        text = '\n'.join("OpenSees_PROGRAM=$(HOME)/bin/OpenSeesSP" if line.startswith("OpenSees_PROGRAM") else line
                              for line in text.splitlines())
        text = '\n'.join("PROGRAMMING_FLAG = -D_PARALLEL_PROCESSING" if line.startswith("PROGRAMMING_FLAG") else line
                              for line in text.splitlines())
        text = '\n'.join("PARALLEL_LIB = $(FE)/system_of_eqn/linearSOE/sparseGEN/DistributedSparseGenColLinSOE.o $(FE)/system_of_eqn/linearSOE/sparseGEN/DistributedSuperLU.o $(FE)/system_of_eqn/linearSOE/sparseGEN/SparseGenColLinSolver.o $(DISTRIBUTED_SUPERLU_LIBRARY)" if line.startswith("PARALLEL_LIB") else line
                              for line in text.splitlines())
        f=open("Makefile.def", 'w')
        f.write(text)
        f.close()
        cmd="make wipe;make;"
        run_cmd(cmd,log_all=True,simple=True,log_output=True)

        

