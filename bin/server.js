#!/usr/bin/env node

const express = require( 'express' );

const articles = require( '../src/articles' );

const app = express();

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

app.get( '/categories/:category/offset', async function( req, res ) {

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

app.get( '/categories/:category/offset/:offset', async function( req, res ) {

try
{
res.json( await articles.getArticleForCategoryAtIndex( req.params.category, req.params.offset ) );
}
catch( error )
{
console.error( error );
res.status(503).json( { error: { message: error.message } } );
}

} );

app.listen( 1992 );
