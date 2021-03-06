#!/usr/bin/env python3

'''
PGS: Programming Grader Shell Tool

This is a command line tool that aids the grading process of programming
assignment/labs by providing the following functionalities:
    * Traverse lab directories and files
    * Support anonymized grading
    * Next/prev student
    * List/open files
    * Set input/output files
    * Mark/classify directories/files for compilation
    * Compile program
    * Run program

A text configuration file is used to specify the list of students
(with unique identifiers) to consider during grading.
From the student info file, the ID is used to run
corresponding lab from the labs directory.

Example:
python3 pgs.py --help
python3 pgs.py -s

Todo:
    * Manual
    * Configuration file
    * Clean code
    * Change system calls to subprocess
    * Refactor framework to behave like a shell with custom commands,
      commands that are not part of the framework are passed directly
      to the underlying shell. Maybe it is better to make real shell
      commands prepend an 'l' similar to sftp.
    * Design GUI interface (ncurses, qt, gtk)
'''

import os
import sys
import argparse
from argparse import RawTextHelpFormatter
import re
import shutil
import zipfile
import tarfile
import rarfile
import gzip
import bz2
import subprocess
import signal


# Global build options, supports C++ and Python
cplusplus = False
'''bool: Default enable/disable C++ compiler'''

sourcext = []
'''list: Default file extensions supported'''

compiler = ''
'''str: Default compiler'''

buildflags = ''
'''str: Default common compiler build flags'''


# Global variables
labdir = ''
'''str: Directory with all students compressed labs'''

workdir = ''
'''str: Working directory for running labs'''

studfile = ''
'''str: File with students info'''

studsel = ''
'''str: Student ID to start processing'''

infiles = []
'''list: Input files for programs'''

force = False
'''bool: Flag, if set overwrite labs even if exists'''

display = False
'''bool: Flag, if set display student file info and exit'''

clean = False
'''bool: Flag, if set all labs in working directory are deleted'''

proclist = []
'''list: Subprocess handles, enable signal communication (e.g., kill)'''


def parseArgs():
    '''
    Parse and validate command line arguments.
    '''
    parser = argparse.ArgumentParser(prog=__file__,
             description='PGS: Programming Grader Shell Tool',
             formatter_class=RawTextHelpFormatter)

    parser.add_argument('-d', '--labdir', type=str, dest='labdir',
                        default=os.getcwd(),
                        help='Directory with compressed labs\n'
                             'Default is \'' + os.getcwd() + '\'')

    parser.add_argument('-w', '--workdir', type=str, dest='workdir',
                        default=os.getcwd(),
                        help='Working directory for running labs\n'
                             'Default is \'' + os.getcwd() + '\'')

    parser.add_argument('-l', '--studfile', type=str, dest='studfile',
                        default='',
                        help='File with student info')

    parser.add_argument('-s', '--studsel', type=str, dest='studsel',
                        default='',
                        help='student ID to start processing')

    # Method 1 uses -i for each file
    # Method 2 uses single -i with multiple files which permits bash regex
    # Both are lists so does not affect program
    # parser.add_argument('-i', '--infile', type=str, action='append', default='',
    #                     dest="infiles", help="input file for student programs")
    parser.add_argument('-i', '--infiles', type=str, nargs='+', default='',
                        dest="infiles", help="input files for student programs")
    parser.add_argument('-f', '--force', action='store_true',
                        dest='force', help='uncompress labs even if exists')
    parser.add_argument('-y', '--display', action='store_true',
                        dest='display', help='display student file info and exit')
    parser.add_argument('-c', '--clean', action='store_true',
                        dest='clean', help='clean (delete) all labs in working directory and exit')
    parser.add_argument('-p', '--compiler', type=str, default='g++',
                        dest='compiler', help='compiler program for building')

    args = parser.parse_args()

    # Set global variables with parsed arguments
    global labdir, workdir, studfile, studsel, infiles, force, display, clean, compiler
    labdir = os.path.abspath(args.labdir)
    workdir = os.path.abspath(args.workdir)
    if args.studfile:
        studfile = os.path.abspath(args.studfile)
    studsel = args.studsel
    for ifile in args.infiles:
        infiles.append(os.path.abspath(ifile))
    force = args.force
    display = args.display
    clean = args.clean
    compiler = args.compiler

    # Build options for C++ and Python
    global cplusplus, python, sourcext, buildflags
    if compiler in ["g++"]:
        cplusplus = True
        python = False
        sourcext = [".cpp", ".c"]
        buildflags = "-Wall -Wextra -pedantic -o prog"
    elif compiler in ["python3"]:
        cplusplus = False
        python = True
        sourcext = [".py"]
        buildflags = ''
    else:
        print("*** Error: unsupported compiler selected ***\n")
        return False
    return True


class Student(object):
    '''
    Student object
    '''
    # Constructor
    def __init__(self, sid='', fn='', labfile=[], pos=-1):
        self.sid = sid
        self.fn = fn
        self.lab = labfile
        self.pos = pos

    # Print student info
    # If multiple lab files, 'idx' is used to specify a lab to print
    def print(self,idx=-1):
        print()
        if idx == -1: lab = ", ".join([os.path.basename(l) for l in self.lab])
        else: lab = ", ".join([os.path.basename(self.lab[idx])])
        print(str(self.pos + 1) + ". " + self.fn + " (" + self.sid + ") --> [" + lab + "]\n")


def loadStudents():
    '''
    Create list of Student objects using the file with students info
    and the students lab submissions. Moves to working directory.
    '''
    os.chdir(workdir)  # move to working directory

    # Load students labs into local variable
    labs = os.listdir(labdir)

    # Load students file contents into local variable
    # Skip student entry if begins with '#'
    studDB = []    # student entry database
    studlist = []  # list of Student objects
    if studfile:
        fo = open(studfile, "r")
        studDB = findPatterns(["^(?!\s*#+)"], fo.readlines())
        fo.close()
        print("Grading Program (auto mode)")
    # Run program manually
    else:
        print("Grading Program (manual mode)")
        studlist.append(Student('unknown', 'Foo Bar', labs))

    # Traverse each student file entry from database
    pos = selflag = 0
    for stud in studDB:
        # Split student entry into form [ID, FIRSTNAME, LASTNAME]

        # TODO: use delimited format (tsv or csv) to allow compound first and last names.
        #sid, fn, ln = stud.split()
        #name = fn + ' ' + ln

        # NOTE: Temp fix to delimited format
        studfields = stud.split()
        nstudfields = len(studfields)
        if nstudfields == 1:
            sid = studfields
            fn = ln = name = ''
        elif nstudfields == 2:
            sid, fn = studfields
            ln = ''
            name = fn
        elif nstudfields == 3:
            sid, fn, ln = studfields
            name = fn + ' ' + ln
        else:
            sid, fn = studfields[0:2]
            ln = ' '.join(studfields[2:nstudfields])
            name = fn + ' ' + ln

        # Load all students or Load selected student and all afterwards
        if (not studsel) or (studsel and (findPatterns([studsel], [sid]) or selflag)):
            # Search for current student lab based on the ID, use first match
            lab = findPatterns([sid], labs)
            labfile = [os.path.join(labdir, ''.join(l)) for l in lab] if lab else []

            # Add Student object to list
            sobj = Student(sid, name, labfile, pos)
            studlist.append(sobj)
            pos = pos + 1
            selflag = 1

    return studlist


def findPatterns(patterns=[], alist=[], mexact=0):
    '''
    Given a series of regex patterns remove all strings that match in the given list
    '''
    # Traverse given patterns
    filtlist = []  # filtered list
    for p in patterns:
        if not mexact: regex = re.compile(p, re.IGNORECASE)
        else: regex = re.compile(r"\b{0}\b".format(p))
        for l in alist:
            if regex.search(l): filtlist.append(l)

    return filtlist


def processStudents(studlist=None):
    '''
    Process students lab assignments (uncompress/copy, compile, run)
    '''
    os.chdir(workdir)  # move to working directory

    if clean: print("Cleaning workspace: " + workdir)

    # Traverse student list
    misslist = []  # list for students with no lab submission
    for stud in studlist:
        # Clean student lab from working directory
        if clean:
            if os.path.exists(stud.sid): shutil.rmtree(stud.sid)
            continue

        # Display student info, do not process
        if display:
            stud.print()
            if not stud.lab:
                misslist.append(stud)
            continue

        # If no lab submission, add student to miss list and skip
        if not stud.lab:
            stud.print()
            print("*** Warning: no lab found for student ***\n")
            misslist.append(stud)
            continue

        # Iterate through each lab of current student
        nlabs = len(stud.lab)
        for i in range(nlabs):
            # Prompt user to process lab submission until user wants
            while True:
                stud.print(i)
                iquery = "RUN LAB? [y]es, [n]o, e[x]it: "
                res = input(iquery).lower()
                while not res in ['y', 'n', 'x']:
                    res = input(iquery).lower()
                print()

                if res in ['x']:
                    # Close files opened for current user
                    subprockill(proclist)
                    return  # quit program

                if res in ['n']: break   # go to next student

                # Uncompress/copy lab and run
                if extractLab(stud,i): processLab(stud)
                os.chdir(workdir)  # move back to working directory

            # Close files opened for current user
            subprockill(proclist)

    # Print students missing lab submissions
    if misslist:
        print("\n\n*** Students missing lab ***\n")
        for stud in misslist: stud.print()


def extractLab(stud=None,i=0):
    '''
    Uncompress/copy lab submission and moves into lab directory
    '''
    # Set lab for processing
    studlab = stud.lab[i]

    # Get file extension from lab submission
    filenm, filext = os.path.splitext(studlab)
    filext = filext.lower()

    # Special case of file extension pair, .tar.*
    extpair = False
    if ".tar." in studlab:
        extpair = True
        filenm, filext2 = os.path.splitext(filenm)
        filext2 = filext2.lower()
        filext = ''.join([filext2, filext])

    # Check status of running directory for current student
    rundir = stud.sid  # running directory same as student ID
    existflag = os.path.exists(rundir)
    if existflag and not force:
        os.chdir(rundir)
        print("*** lab running directory...exists ***")
        return True
    elif existflag and force:
        shutil.rmtree(rundir)  # delete lab directory
        print("*** lab running directory...overwritten ***")
    else:
        print("*** lab running directory...created ***")

    # If a compressed file, create running directory and move into it
    if filext:
        os.mkdir(rundir)
        os.chdir(rundir)
    # If lab is uncompressed, move to working directory
    else:
        os.chdir(workdir) # move into working directory

    try:
        # If not a compressed file, copy lab and move into it
        if not filext:
            shutil.copytree(studlab, rundir)
            os.chdir(rundir)
        # If a ZIP file
        elif filext in [".zip"]:
            lab = zipfile.ZipFile(studlab, 'r')
            lab.extractall()
        # If a RAR file
        elif filext in [".rar"]:
            lab = rarfile.RarFile(studlab, 'r')
            lab.extractall()
        # If a TAR/TGZ/TBZ2 file
        elif filext in [".tar", ".tgz", ".tbz2", ".tar.gz", ".tar.bz2"]:
            # If extension pair
            if filext in [".tgz", ".tbz2"]: extpair = True
            if extpair:
                # Uncompressed content in binary form
                if filext in [".tar.gz", ".tgz"]: cd = gzip.open(studlab, "rb")
                elif filext in [".tar.bz2", ".tbz2"]: cd = bz2.open(studlab, "rb")
                # Write uncompressed content as TAR archive
                studlab = os.path.split(filenm + ".tar")[1]
                tfd = open(studlab, "wb")
                tfd.write(cd.read())
                tfd.close()
            # Extract TAR archive
            lab = tarfile.open(studlab)
            lab.extractall()
            lab.close()
            if extpair: os.remove(studlab)
        # If unknown compression type
        else:
            print("*** unknown extension (under construction): " + filext + " ***\n")
            return False
    except:
        # If failed to uncompress/copy lab, rollback and stop
        print("*** Error: failed to uncompress/copy lab ***\n")
        os.chdir(workdir)
        shutil.rmtree(rundir)
        return False
    return True


def viewerSelect(afile=''):
    '''
    Given a file, use its extension to select a viewer program for opening the file.
    The function builds a command line string that is executed via system command.
    '''
    # Parse file extension
    filenm, filext = os.path.splitext(afile)
    filext = filext.lower()

    # If a valid C/C++ source file
    if filext in [".cpp", ".hpp", ".c", ".h"]:
        viewer = "/usr/bin/gedit"
        opts = ''
        #opts = "-lcpp"
    # If a valid Python script file
    elif filext in [".py"]:
        viewer = "/usr/bin/gedit"
        opts = ''
        #viewer = "notepad++"
        #opts = "-lpython"
    # If a Microsoft Word file
    elif filext in [".doc", ".docx", ".rtf", ".odt"]:
        viewer = "/usr/bin/lowriter"
        opts = ''
        #viewer = "/cygdrive/c/Program Files/Microsoft Office 15/root/office15/WINWORD.EXE"
    # If a Microsoft Excel file
    elif filext in [".xlsx"]:
        viewer = "/usr/bin/localc"
        opts = ''
        #viewer = "/cygdrive/c/Program Files/Microsoft Office 15/root/office15/EXCEL.EXE"
    # If a PDF file
    elif filext in [".pdf"]:
        viewer = "/usr/bin/evince"
        opts = ''
        #viewer = "/cygdrive/c/Program Files (x86)/Adobe/Acrobat Reader DC/Reader/AcroRd32.exe"
    # If an image file
    elif filext in [".jpg", ".png"]:
        viewer = "/usr/bin/gpicview"
        opts = ''
        #viewer = "/cygdrive/c/WINDOWS/System32/mspaint.exe"
    # If a video file
    elif filext in [".mp4", ".avi"]:
        viewer = "/usr/bin/vlc"
        opts = ''
    # If unknown file type, assume it is a text file
    else:
        viewer = "/usr/bin/gedit"
        opts = ''
        #viewer = "notepad++"
        #opts = "-lnormal"

    # Open file, redirect stdout/stderr to /dev/null
    cmd = "\"" + viewer + "\" " + opts + " \"" + afile + "\""
    proclist.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, shell=True))


def compileLab(afile='', inc=''):
    '''
    Compile lab source codes, one source file at a time
    '''
    # Only use include directories for C++ programs
    if not cplusplus: inc = ''

    # Set attempt limit for compiling program
    maxattempts = 3;
    attempts = 0;
    while attempts < maxattempts:
        try:
            # Prompt user to compile/run lab
            while True:
                iquery = "RUN PROG? [y]es, [n]o, [i]nfiles --> " + afile + ": "
                resstr = input(iquery)
                if not resstr: continue
                reslist = resstr.split()
                res = reslist[0].lower()
                while not res in ['y', 'n', 'i']:
                    resstr = input(iquery)
                    if not resstr: continue
                    reslist = resstr.split()
                    res = reslist[0].lower()

                # Print input files if selected
                if res in ['i']:
                    for i in range(len(infiles)):
                        print(str(i) + ' ' + infiles[i])
                    continue

                # Check if input file was selected
                infile = ''
                if len(reslist) == 2:
                    # Validate file index
                    inpidx = int(reslist[1])
                    if inpidx < 0 or inpidx >= len(infiles):
                        print("*** Warning: index for input file is out of range ***\n")
                        continue

                    # Get file and validate
                    infile = infiles[inpidx]
                    if not os.path.exists(infile):
                        print("*** Warning: input file does not exist ***\n")
                        continue

                # Stop using file
                if res in ['n']:
                    attempts = maxattempts
                    break

                # Compile and run program
                cmd = compiler + ' ' + buildflags + ' ' + inc + ' ' + afile
                print("\n*** compiling: " + cmd + " ***\n")
                if cplusplus:
                    if not os.system(cmd):
                        progname = "prog"
                        cmd2 = "./" + progname
                        if infile:
                            ifd = open(infile, 'r')
                            subprocess.run(cmd2, stdin=ifd, shell=True)
                            ifd.close()
                        else:
                            subprocess.run(cmd2, shell=True)
                        os.remove(progname)
                        attempts = 0;
                        print()
                    else:
                        attempts = attempts + 1
                elif python:
                    subprocess.run(cmd, shell=True)
                    print()
                else:
                    os.system(cmd)
                    print()
        except:
            print("\n*** Error: compile/run failed for " + afile + " ***\n")
            attempts = attempts + 1


def parseRelPaths(root='', basepaths=[], rellists=[], dir_file='', mexact=0):
    '''
    Parse a root path based on a match with a base path to obtain a relative path.
    The relative path is prefix to the given directory or file and stored in lists.
    '''
    # Iterate through all base paths
    for i in range(len(basepaths)):
        # Check if base path is subdirectory of root
        if findPatterns([basepaths[i]],[root], mexact):
            # Split root paths by '/'
            splitdir = root.split('/')
            # Find index in split paths where base path is found
            idx = splitdir.index(basepaths[i])
            # Join all split paths after base path index
            if (idx+1) < len(splitdir):
                rellists[i].append('/'.join(splitdir[idx+1:]) + '/' + dir_file)
            else: rellists[i].append(dir_file)
            return True
    return False


def processLab(stud=None):
    '''
    Search student lab directory for source files
    '''
    pidx = 0  # part number
    partdirs = [[] for i in range(2)]  # store directories for lab parts
    partfiles = [[] for i in range(2)]  # store source files for lab parts
    partbases = []  # store the base directories for lab parts

    # Check if current directory is itself a lab part
    print()
    if len(os.listdir()) > 0:
        print(os.path.basename(os.getcwd()) + '/' + str(os.listdir()))
    iquery = "USE DIRECTORY? [y]es, [n]o, [c]ompile, e[x]it --> " + os.path.basename(os.getcwd()) + ": "
    res = input(iquery).lower()
    while not res in ['y', 'n', 'c', 'x']:
        res = input(iquery).lower()
    if res in ['c']:  # consider subdirectory as a compilation part
        partdirs[pidx].append(os.getcwd())    # add to top parts directories
        partbases.append(os.path.basename(os.getcwd()))  # add to base parts directories
        pidx = pidx + 1  # part number
    elif res in ['n', 'x']: return  # exit processing lab

    # Traverse the lab directory tree
    for root, dirs, files in os.walk(os.getcwd()):
        # Move to current root directory
        os.chdir(root)

        # Make a temporary root using current root
        troot = root.replace(workdir,'')
        if troot.startswith("/"): troot = troot[1:]  # remove initial backslash

        # Prune hidden/temporary/MACOSX directories
        for p in findPatterns(["^(\s*[.~]+)", "MACOSX"], dirs): dirs.remove(p)

        # Print directories available
        #print()
        #if len(dirs) > 0: print(troot + '/' + str(dirs))

        # Traverse subdirectories to prune
        tdirs = dirs[:]  # get copy of subdirectory list, slice
        for d in tdirs:
            # Print files inside current directory
            print()
            if len(os.listdir(d)) > 0:
                print(os.path.basename(os.getcwd()) + '/' + d + '/' + str(os.listdir(d)))
            iquery = "USE DIRECTORY? [y]es, [n]o, [c]ompile, e[x]it --> " + d + ": "
            res = input(iquery).lower()
            while not res in ['y', 'n', 'c', 'x']:
                res = input(iquery).lower()
            if res in ['n']: dirs.remove(d)  # prune current subdirectory
            elif res in ['c']:  # consider subdirectory as a compilation part
                # Check if directory needs to be included for parts compilation
                if not parseRelPaths(troot, partbases, partdirs, d):
                    partdirs[pidx].append(root + '/' + d)    # add to top parts directories
                    partbases.append(d)  # add to base parts directories
                    pidx = pidx + 1  # part number
            elif res in ['x']: return  # exit processing lab

        # Prune hidden/temporary/executable files
        for p in findPatterns(["^(\s*[.~]+)","[.]exe$"], files): files.remove(p)

        # Traverse files to open/compile
        for afile in files:
            iquery = "OPEN FILE? [y]es, [n]o, e[x]it --> " + troot + '/' + afile + ": "
            res = input(iquery).lower()
            while not res in ['y', 'n', 'x']:
                res = input(iquery).lower()
            # View source file
            if res in ['y']: viewerSelect(afile)
            elif res in ['x']: return  # exit processing lab

            # Check if source file, compile or add to compilation parts
            filenm, filext = os.path.splitext(afile)
            filext = filext.lower()
            print(pidx)
            if filext in sourcext:
                if not pidx: compileLab('\"' + afile + '\"')
                else: parseRelPaths(troot, partbases, partfiles, afile, 1)

    # Compile each lab part, if necessary
    for i in range(pidx):
        print("\nCompiling lab part " + str(i+1))
        os.chdir(partdirs[i][0])

        # Concatenate include directories and source files
        incdirs = '-I\"' + '\" -I\"'.join(partdirs[i][:]) + '\"'
        srcfiles = '\"' + '\" \"'.join(partfiles[i]) + '\"'
        compileLab(srcfiles, incdirs)


def subprockill(plist):
    '''
    Kill all active child processes
    '''
    for p in plist: p.kill()


'''
Main entry point
'''
if __name__ == "__main__":
    if parseArgs():
        processStudents(loadStudents())

