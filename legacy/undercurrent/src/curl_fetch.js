const { execFile } = require( 'child_process' );
const cheerio = require( 'cheerio' );

const DEFAULT_UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36';

function runCurl( url )
{
return new Promise( function( resolve, reject ) {

const ua = process.env.USER_AGENT || DEFAULT_UA;

execFile(
'curl',
[ '-fsSL', '--max-time', '30', '-A', ua, url ],
{ maxBuffer: 10 * 1024 * 1024 },
function( error, stdout, stderr ) {
if( error )
{
reject( new Error( `curl failed (${error.code || error.message}) for ${url}` ) );
return;
}
resolve( stdout );
}
);

} );
}

module.exports = {
getHTMLForURL: async function( url )
{
return cheerio.load( await runCurl( url ) );
}
};
