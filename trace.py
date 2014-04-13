#!/usr/bin/env python
import pycparser
from pycparser.c_ast import *
import sys
import struct
import pickle
import ast_ops

IDSZ = ast_ops.sizeof("char")
PTRSZ = ast_ops.sizeof("void *")
INTSZ = ast_ops.sizeof("int")
print IDSZ,PTRSZ,INTSZ

""" A proof-of-concept trace listener for C programs.
This needs to be a lot more efficient (i.e. written in C)
for it to be able to handle an actual C program """

if len(sys.argv) != 3:
  print "Usage: %s symbol_table.pkl debug.fifo"%(sys.argv[0],)
  exit()

sym_table = pickle.load(open(sys.argv[1], 'r'))
fifo = open(sys.argv[2], 'r')

while True:
  data = fifo.read(IDSZ)
  if len(data) == 0:
    fifo.close()
    print "Re-opening fifo..."
    fifo = open(sys.argv[2], 'r')
    continue
  ID = ord(struct.unpack("@c",data)[0])
  fn,coord,var,cls = sym_table[ID]
  if cls in [Assignment, ParamList, Decl]:
    length = ord(struct.unpack("@c", fifo.read(IDSZ))[0])
    #print length
    val = hex(struct.unpack("@P", fifo.read(length))[0])+": "
    length = ord(struct.unpack("@c", fifo.read(IDSZ))[0])
    #print length
    val += str(struct.unpack('@'+'i'*(length/INTSZ), fifo.read(length))[0])
    if cls == Assignment: var = var.lvalue.name
    elif cls == Decl: var = var.name
  elif cls == pycparser.c_ast.FuncDef:  val = "function"
  elif cls == pycparser.c_ast.Return:
    length = ord(struct.unpack("@c", fifo.read(IDSZ))[0])
    #print length
    #print coord
    val = struct.unpack('@'+'i'*(length/INTSZ), fifo.read(length))[0]
  elif cls == UnaryOp:
    val = hex(struct.unpack("@P", fifo.read(PTRSZ))[0])
  else:
    
    val = None
    print "Unhandled type: "+str(cls)
  print "%04d] %s:%d: (%s) %s"%(ID,fn,coord.line,var,str(val))


