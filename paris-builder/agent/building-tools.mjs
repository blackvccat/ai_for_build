/** Read-only architectural evidence tools in the owned DSH runtime. */
import { readFileSync, appendFileSync } from 'node:fs'
import { createHash, randomUUID } from 'node:crypto'
import { join } from 'node:path'
export const name = 'paris-building-tools'
export const inject = ['tools']
export function apply(ctx) {
  const context = JSON.parse(readFileSync(process.env.PARIS_AGENT_CONTEXT, 'utf8'))
  if (['intent', 'annotation', 'brief'].includes(process.env.PARIS_AGENT_PHASE)) return
  if (['generator_repair', 'framework_planning'].includes(process.env.PARIS_AGENT_PHASE)) {
    const files = context.generator_sources.files
    const source = file => {
      if (!files.includes(file) || file.includes('/') || file.includes('\\')) throw new Error('Unknown generator module')
      return readFileSync(join(context.generator_sources.root, file), 'utf8')
    }
    const tool = (name, description, properties, required, execute) => ctx.tools.register({
      name, description,
      parameters: {type:'object',properties,required,additionalProperties:false},
      output: {schema:{type:'object',properties:{json:{type:'string'}},required:['json'],additionalProperties:false},
        render: (_args,value)=>[{type:'text',text:value.json}]},
      async execute(args, execution) {
        execution.signal.throwIfAborted()
        const record={id:randomUUID(),tool:name,at:new Date().toISOString(),inputs:args}
        try {
          const output=execute(args), json=JSON.stringify(output)
          appendFileSync(process.env.PARIS_AGENT_TOOL_LOG,JSON.stringify({...record,status:'SUCCEEDED',output,
            sha256:createHash('sha256').update(json).digest('hex')})+'\n','utf8')
          return {json}
        } catch(error) {
          appendFileSync(process.env.PARIS_AGENT_TOOL_LOG,JSON.stringify({...record,status:'FAILED',error:String(error)})+'\n','utf8')
          throw error
        }
      }
    })
    tool('generator_source_map','Read editable generator modules, dispatch roles and actual review failures.',{},[],()=>({
      files:files.map(file=>({file,lines:source(file).split('\n').length})),roles:context.module_roles,
      failures:context.failures,validation_feedback:context.validation_feedback}))
    tool('read_generator_source','Read exact source text with line numbers from a task-local generator snapshot.',
      {file:{type:'string',enum:files},start:{type:'integer',minimum:1},end:{type:'integer',minimum:1}},['file','start','end'],args=>{
        if(!Number.isInteger(args.start)||!Number.isInteger(args.end)||args.start<1||args.end<args.start||args.end-args.start>250)
          throw new Error('Read a valid range of up to 251 lines')
        const lines=source(args.file).split('\n')
        return {file:args.file,start:args.start,end:Math.min(args.end,lines.length),
          source:lines.slice(args.start-1,args.end).join('\n')}
      })
    tool('search_generator_source','Find literal text in generator source and locate active dispatch and geometry functions.',
      {query:{type:'string',minLength:1}},['query'],args=>{
        if(typeof args.query!=='string'||!args.query)throw new Error('Search query required')
        return {matches:files.flatMap(file=>source(file).split('\n').flatMap((line,index)=>
          line.includes(args.query)?[{file,line:index+1,text:line}]:[]))}
      })
    return
  }
  const register = (name, description, field) => {
    ctx.tools.register({
      name, description,
      parameters: { type: 'object', properties: {}, additionalProperties: false },
      output: { schema: { type: 'object', properties: { json: { type: 'string' } }, required: ['json'], additionalProperties: false },
        render: (_args, value) => [{ type: 'text', text: value.json }] },
      async execute(args, execution) {
        execution.signal.throwIfAborted()
        const record = { id: randomUUID(), tool: name, at: new Date().toISOString(), inputs: args }
        try {
          if (!args || Object.keys(args).length) throw new Error('This evidence tool takes no arguments')
          if (!(field in context)) throw new Error('Required evidence context is unavailable')
          const json = JSON.stringify(context[field])
          appendFileSync(process.env.PARIS_AGENT_TOOL_LOG, JSON.stringify({ ...record, status: 'SUCCEEDED',
            output: context[field], sha256: createHash('sha256').update(json).digest('hex') }) + '\n', 'utf8')
          return { json }
        } catch (error) {
          appendFileSync(process.env.PARIS_AGENT_TOOL_LOG, JSON.stringify({ ...record, status: 'FAILED', error: String(error) }) + '\n', 'utf8')
          throw error
        }
      },
    })
  }
  register('architecture_catalog', 'Read supported forms, facade schemes, techniques and size limits before planning.', 'catalogue')
  register('source_evidence', 'Read four-layer retrieval evidence. IDs, constraints and hashes are authoritative; similarity is not quality.', 'knowledge')
  register('real_architecture_sources', 'Read cited real architectural observations, separately from Minecraft design inference.', 'reality')
}
