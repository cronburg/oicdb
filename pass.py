#!/usr/bin/env python
import pycparser
from pycparser import parse_file, c_generator
from pycparser.c_ast import *
import ast_ops
import sys
import pickle
import copy
import subprocess

sym_table = dict()
ID_count = 0

def get_ast(fn, cpp_path='cpp'):
  return parse_file(fn, use_cpp=True, cpp_path=cpp_path, \
                    cpp_args=r'-Ifake_libc')

setup_rubric = pickle.loads(open("rubrics/setup.pkl", 'r').read())
def setup_pass(ast, filename=""):
  """ Insert setup expressions into main() as necessary """
  rubric = setup_rubric
  #print ast.ext
  result = []
  for c in ast.ext:
    # Find main():
    if isinstance(c, pycparser.c_ast.Typedef):
      continue
    elif isinstance(c, pycparser.c_ast.FuncDef) and c.decl.name == 'main':
      # Append setup expressions to beginning of main() block items list:
      c.body.block_items = rubric.block_items + c.body.block_items
    result.append(c)
  ast.ext = result
  #print ast.ext
  
# Updates the symbol table to include the new unique key. Return the new
# ID_count so the caller knows the ID for the new symbol / assignment.
def new_sym(unique_key):
  global ID_count, sym_table
  ID_count = ID_count + 1
  sym_table[ID_count] = unique_key
  return "__DEBUG_"+str(ID_count)

def var_declare(name, rubric, num):
  decl = copy.deepcopy(rubric.block_items[num])
  try:
    decl.init.expr.value = str(ID_count)
  except AttributeError:
    decl.init.value = str(ID_count)
  decl.type.declname = name
  return decl

fncn_rubric = pickle.loads(open("rubrics/fncn.pkl", 'r').read())
def fncn_pass(ast, filename=""):
  """ Insert 'entering' and 'exiting' fncn expressions """
  rubric = fncn_rubric
  
  # Find and debug entrance and void exit of all function definitions:
  def dbg(c):
    rubric_loc = copy.deepcopy(rubric)
    name = new_sym((filename,c.coord,c.decl.name,type(c)))
    decl = var_declare(name, rubric_loc, 0)
    ast_ops.sar_string(rubric_loc, "__DEBUG_ID", name)
    f_in = rubric_loc.block_items[1]
    f_out = rubric_loc.block_items[2]
    c.body.block_items = [decl,f_in] + c.body.block_items + [f_out]
    return c
  ast_ops.sar(ast, pycparser.c_ast.FuncDef, dbg)

return_rubric = pickle.loads(open("rubrics/return.pkl", 'r').read())
def return_pass(ast, filename=""):
  """ Insert 'exiting' fncn expressions at return statements """
  rubric = return_rubric
  
  # Find and debug all return statements:
  def dbg(ret):
    rubric_loc = copy.deepcopy(rubric)
    name = new_sym((filename,ret.coord,"return",type(ret)))
    decl = var_declare(name, rubric_loc, 0)
    ast_ops.sar_string(rubric_loc, "__DEBUG_ID", name)
    fncn_out = rubric_loc.block_items[2]
    decl2 = var_declare("__DEBUG_RETURN", rubric, 1)
    decl2.init = ret.expr
    ret.expr = pycparser.c_ast.ID("__DEBUG_RETURN")
    fncn_ret = rubric_loc.block_items[5]
    return Compound([decl,decl2,fncn_out,rubric_loc.block_items[3],\
                     rubric_loc.block_items[4],fncn_ret,ret],coord=ret.coord)
  ast_ops.sar(ast, pycparser.c_ast.Return, dbg)


var_rubric = pickle.loads(open("rubrics/var.pkl", 'r').read())
def var_pass(ast, filename=""):
  """ Insert assignment to variable logging expressions """
  rubric = var_rubric
  ast_ops.fix_typeofs(rubric)
  
  def dbg(a):
    a.rvalue = ast_ops.sar(a.rvalue, Assignment, dbg)
    a.lvalue = ast_ops.sar(a.lvalue, Assignment, dbg)
    r = copy.deepcopy(rubric)
    ast_ops.sar(r, Constant, lambda c: Constant('int',str(ID_count+1)) if c.value=='0' else c)
    ast_ops.sar_string(r, "__DEBUG_ID", new_sym((filename,a.coord,a,type(a))))
    ast_ops.sar_ID(r, "LVALUE", a.lvalue)
    ast_ops.sar_ID(r, "RVALUE", a.rvalue)
    #print "OPERATION: "+a.op
    r.block_items[-2].op = a.op # makes the operation (=, +=, -=) correct - TODO: magic number...
    return FuncCall(ID(""), ExprList([Compound(r.block_items, coord=a.coord)], coord=a.coord))
  ast_ops.sar(ast, Assignment, dbg)

param_rubric = pickle.loads(open("rubrics/param.pkl", 'r').read())
def param_pass(ast, filename=""):
  """ Insert parameter declaration logging expressions """
  rubric = param_rubric
  ast_ops.fix_typeofs(rubric)

  def dbg(f):
    #print f.__dict__
    args = [d.name for d in f.decl.type.args.params]
    for arg in args[::-1]:
      r = copy.deepcopy(rubric)
      ast_ops.sar(r, Constant, lambda c: Constant('int',str(ID_count+1)) if c.value=='0' else c)
      ast_ops.sar_string(r, "__DEBUG_ID", new_sym((filename,f.coord,arg,type(f.decl.type.args))))
      ast_ops.sar_string(r, "LVALUE", arg)
      ast_ops.sar_string(r, "RVALUE", arg)
      f.body.block_items.insert(0,r)
    return f

  ast_ops.sar(ast, FuncDef, dbg)

def decl_pass(ast, filename=""):
  rubric = var_rubric
  
  def dbg(d):
    if not d.__dict__.has_key("init"): return None # not the kind of Decl we're looking for
    if d.name.startswith("__DEBUG_"): return None # skip VAR pass variables
    d.init = ast_ops.sar(d.init, Decl, dbg)
    r = copy.deepcopy(rubric)
    ast_ops.sar(r, Constant, lambda c: Constant('int',str(ID_count+1)) if c.value=='0' else c)
    ast_ops.sar_string(r, "__DEBUG_ID", new_sym((filename,d.coord,d,type(d))))
    ast_ops.sar_string(r, "LVALUE", d.name)
    if d.init: ast_ops.sar_ID(r, "RVALUE", d.init)
    # No initial value, so RVALUE = *LVALUE implicitly (garbage value, but useful for debugging):
    else: ast_ops.sar_string(r, "RVALUE", d.name)
    return FuncCall(ID(""), ExprList([Compound(r.block_items, coord=d.coord)], coord=d.coord))
  def dbg_c(c):
    for i in range(len(c.block_items))[::-1]:
      bi = c.block_items[i]
      if isinstance(bi, Decl):
        ret = dbg(bi)
        if ret != None: c.block_items.insert(i+1,ret)
    c.block_items = map(lambda bi: ast_ops.sar(bi, Compound, dbg_c), c.block_items)
    return c
  ast_ops.sar(ast, Compound, dbg_c)

unary_rubric = pickle.loads(open("rubrics/unary.pkl", 'r').read())
def unary_pass(ast, filename=""):
  rubric = unary_rubric
  ast_ops.fix_typeofs(rubric)

  def dbg(u):
    #print u.op
    if not ("++" in u.op or "--" in u.op): return u
    r = copy.deepcopy(rubric)
    def fix_op(ur):
      if "++" in ur.op or "--" in ur.op: ur.op = u.op
      return ur
    ast_ops.sar(r, UnaryOp, fix_op)
    ast_ops.sar(r, Constant, lambda c: Constant('int',str(ID_count+1)) if c.value=='0' else c)
    ast_ops.sar_string(r, "__DEBUG_ID", new_sym((filename,u.coord,u,type(u))))
    #print u.expr.__dict__
    ast_ops.sar_ID(r, "LVALUE", u.expr)
    return FuncCall(ID(""), ExprList([Compound(r.block_items, coord=u.coord)], coord=u.coord))

  ast_ops.sar(ast, UnaryOp, dbg)

def to_c(ast):
  gen = c_generator.CGenerator()
  return gen.visit(ast)

if __name__ == '__main__':

  if len(sys.argv) < 2:
    print ("Usage: %s file.c [sym_table.pkl]"%sys.argv[0])
    exit()

  fn = sys.argv[1]
  sym_table_fn = fn + ".sym.pkl"
  if len(sys.argv) > 2: sym_table_fn = sys.argv[2] + ".sym.pkl"

  ast = get_ast(fn)

  # Do VAR pass first (don't want to VAR the setup)
  passes = [var_pass, unary_pass, decl_pass, param_pass, fncn_pass, return_pass, setup_pass]
  #passes = [var_pass, param_pass, fncn_pass, return_pass, setup_pass]
  map(lambda ps: ps(ast, filename=fn), passes)

  # TODO: get rid of this hacky line:
  print (subprocess.check_output("cat %s | egrep '^#include'"%(sys.argv[1],), shell=True)).rstrip()
  print "#include <unistd.h>"
  print "#include <fcntl.h>"
  print "int __DEBUG_FIFO;"
  print (to_c(ast))
  pickle.dump(sym_table, open(sym_table_fn, 'w'))

