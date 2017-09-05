'''
Student object
'''
class Student(object):
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
