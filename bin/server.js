#!/usr/bin/env node

const express = require( 'express' );

const articles = require( '../src/articles' );

const app = express();

app.get( '/', function( req, res ) {

res.redirect( 302, '/categories' );

} );

app.get( '/categories', async function( req, res ) {

try
{
res.json( await articles.getAvailableCategories() );
}
catch( error )
{
console.error( error );
res.status(503).json( { error: { message: error.message } } );
}

} );

app.get( '/categories/:category', async function( req, res ) {

try
{
res.json( await articles.getArticleForCategoryAtIndex( req.params.category, 0 ) );
}
catch( error )
{
console.error( error );
res.status(503).json( { error: { message: error.message } } );
}

} );

app.get( '/categories/:category/offset', function( req, res ) {

res.redirect( 301, `/categories/${encodeURIComponent( req.params.category )}` );

} );

app.get( '/categories/:category/offset/:offset', async function( req, res ) {

const offset = parseInt( req.params.offset, 10 );

if( !Number.isInteger( offset ) || offset < 0 )
{
res.status(400).json( { error: { message: "Invalid offset" } } );
return;
}

try
{
res.json( await articles.getArticleForCategoryAtIndex( req.params.category, offset ) );
}
catch( error )
{
console.error( error );
res.status(503).json( { error: { message: error.message } } );
}

} );

app.listen( process.env.PORT || 1992 );
